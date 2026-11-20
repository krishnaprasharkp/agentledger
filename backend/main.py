from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter_ns

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from fastapi.staticfiles import StaticFiles
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from db_models import AgentEventRecord
from economics import router as analytics_router
from invoice_agent.extractor import ExtractionError, extract_invoice_data
from invoice_agent.pdf_extractor import MAX_PDF_SIZE, extract_pdf_text
from invoice_agent.provider import ProviderError, Telemetry, extract_with_provider, pricing_catalog
from invoice_agent.schemas import InvoiceData, InvoiceValidation
from invoice_agent.validator import validate_invoice
from models import AgentEvent, AgentEventCreate
from invoice_agent.adapter import configured_invoice_deployment, record_invoice_execution
from portfolio import router as portfolio_router
from service_desk_adapter import router as service_desk_router
from support_probe import router as support_probe_router
from security import WorkspaceSecurity
from public_demo import create_public_demo
from settings import Settings, get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    pricing_catalog()
    yield


settings = get_settings()
workspace_key_docs = Depends(APIKeyHeader(name="X-Workspace-Key", auto_error=False))
app = FastAPI(title="AgentLedger API", version="1.0.0", lifespan=lifespan)
app.add_middleware(WorkspaceSecurity, key=settings.workspace_api_key.get_secret_value(),
                   require_key=settings.app_mode == "private")
app.include_router(analytics_router, dependencies=[workspace_key_docs])
app.include_router(portfolio_router, dependencies=[workspace_key_docs])
app.include_router(service_desk_router, dependencies=[workspace_key_docs])
app.include_router(support_probe_router, dependencies=[workspace_key_docs])


@app.get("/app-mode")
def app_mode():
    return {"public_demo": False}


@app.get("/health")
def health():
    return {"status": "healthy", "service": "agentledger-api"}


@app.post("/events", response_model=AgentEvent, status_code=status.HTTP_201_CREATED, dependencies=[workspace_key_docs])
def create_event(payload: AgentEventCreate, db: Session = Depends(get_db)):
    event = AgentEventRecord(**payload.model_dump())
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@app.get("/events", response_model=list[AgentEvent], dependencies=[workspace_key_docs])
def list_events(
    db: Session = Depends(get_db),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0, le=100_000),
):
    statement = select(AgentEventRecord).order_by(
        AgentEventRecord.created_at.desc(), AgentEventRecord.run_id.desc()
    ).offset(offset).limit(limit)
    return db.scalars(statement).all()


@app.post("/invoices/validate", response_model=InvoiceValidation, tags=["Invoice Intelligence"], dependencies=[workspace_key_docs])
def validate_invoice_endpoint(invoice: InvoiceData):
    return validate_invoice(invoice)


def read_pdf(file: UploadFile):
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise ProviderError("invalid_extension", 400, "Only PDF files are supported.")
    pdf_bytes = file.file.read(MAX_PDF_SIZE + 1)
    return extract_pdf_text(pdf_bytes)


@app.post("/invoices/upload", tags=["Invoice Intelligence"], dependencies=[workspace_key_docs])
def upload_invoice(file: UploadFile = File(...)):
    try:
        result = read_pdf(file)
    except (ValueError, ProviderError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "filename": file.filename,
        "page_count": result["page_count"],
        "character_count": result["character_count"],
        "text_preview": result["text"][:1000],
        "extraction_status": "success" if result["text"].strip() else "no_extractable_text",
    }


@app.post("/invoices/process", tags=["Invoice Intelligence"], dependencies=[workspace_key_docs])
def process_invoice(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    config: Settings = Depends(get_settings),
):
    deployment = configured_invoice_deployment(db, config.invoice_deployment_id)
    start_ns = perf_counter_ns()
    provider = config.extraction_provider
    telemetry = Telemetry(
        model="rule_based_v1" if provider == "rules" else config.llm_model,
        provider=provider,
    )
    error = validation = None
    try:
        pdf_result = read_pdf(file)
        if provider == "rules":
            invoice = extract_invoice_data(pdf_result["text"])
        else:
            invoice = extract_with_provider(pdf_result["text"], config, telemetry)
        validation = validate_invoice(invoice)
    except ProviderError as exc:
        error = exc
    except ExtractionError:
        error = ProviderError("rule_extraction_failed", 422, "The invoice did not match the baseline format.")
    except ValueError as exc:
        error = ProviderError("invalid_pdf", 422, str(exc))

    event = AgentEventRecord(
        agent_id="invoice-agent-v1",
        model=telemetry.model,
        input_tokens=telemetry.input_tokens or 0,
        output_tokens=telemetry.output_tokens or 0,
        latency_ms=(perf_counter_ns() - start_ns) // 1_000_000,
        status="failure" if error else "success",
        workflow="invoice_process",
        provider=provider,
        model_latency_ms=telemetry.model_latency_ms,
        usage_reported=telemetry.input_tokens is not None and telemetry.output_tokens is not None,
        provider_charge_usd=telemetry.provider_charge_usd,
        estimated_cost_usd=telemetry.estimated_cost_usd,
        pricing=telemetry.pricing,
        provider_request_id=telemetry.provider_request_id,
        validation_passed=validation.is_valid if validation else None,
        requires_human_review=validation.requires_human_review if validation else None,
        error_code=error.code if error else None,
    )
    db.add(event)
    db.flush()
    if deployment:
        record_invoice_execution(db, deployment, event, config.invoice_telemetry_origin)
    db.commit()
    db.refresh(event)

    if error:
        raise HTTPException(
            status_code=error.status,
            detail=str(error),
            headers={"X-Run-ID": str(event.run_id)},
        )

    return {
        "filename": file.filename,
        "page_count": pdf_result["page_count"],
        "invoice": invoice.model_dump(mode="json"),
        "validation": validation.model_dump(),
        "extraction_method": "rule_based_v1" if provider == "rules" else provider,
        "execution": AgentEvent.model_validate(event).model_dump(mode="json"),
    }


if settings.app_mode == "public_demo":
    app = create_public_demo(settings.static_dir)
elif settings.static_dir:
    app.mount("/", StaticFiles(directory=Path(settings.static_dir), html=True), name="dashboard")
