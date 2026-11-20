"""Opt-in OpenAI smoke execution using one fixed synthetic support ticket."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from domain import Deployment, Execution, utc_now
from invoice_agent.provider import ProviderError, Telemetry, pricing_catalog, request_completion
from portfolio import SUPPORT_PROBE_ADAPTER, Db, ExecutionInput, get, save_execution
from settings import Settings, get_settings

router = APIRouter(prefix="/adapters/customer-support", tags=["Customer support provider probe"])
LIMIT = 128
TICKET = "Synthetic ticket: I can open the demo app, but I forgot my password. How do I reset it?"


class ProbeAuthorization(BaseModel):
    authorize_live_request: StrictBool

    @field_validator("authorize_live_request")
    @classmethod
    def require_authorization(cls, value):
        if value is not True:
            raise ValueError("Explicit live request authorization is required.")
        return value


class Classification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Literal["account_access", "billing", "technical", "other"]


def replay(db, deployment_id, attempt_id):
    return db.scalar(select(Execution).where(
        Execution.deployment_id == deployment_id, Execution.external_run_id == str(attempt_id),
    ))


def evidence(telemetry, requested_model, status, error=None, category=None):
    return {
        "kind": "live_provider_synthetic_probe",
        "scenario": "synthetic_support_password_reset_v1",
        "provider": telemetry.provider,
        "status": status,
        "requested_model": requested_model,
        "reported_model": telemetry.model if telemetry.model_reported else None,
        "provider_request_id": telemetry.provider_request_id,
        "provider_http_status": telemetry.provider_http_status,
        "duration_ms": telemetry.model_latency_ms,
        "pricing": telemetry.pricing,
        "error_code": error,
        "classification": category,
    }


@router.post("/deployments/{deployment_id}/synthetic-probes/{attempt_id}")
def run_probe(deployment_id: UUID, attempt_id: UUID, authorization: ProbeAuthorization,
              db: Db, config: Settings = Depends(get_settings)):
    deployment = get(db, Deployment, deployment_id)
    if deployment.adapter != SUPPORT_PROBE_ADAPTER:
        raise HTTPException(422, "Use a dedicated customer_support_probe deployment.")
    existing = replay(db, deployment_id, attempt_id)
    if existing is not None:
        return existing

    if not config.support_live_probe_enabled:
        raise HTTPException(503, "Live support probes are disabled.")
    if not config.llm_api_key.get_secret_value().strip():
        raise HTTPException(503, "An OpenAI API credential is required.")
    if not config.workspace_api_key.get_secret_value().strip():
        raise HTTPException(503, "Protect live probes with a workspace access key.")
    if str(config.llm_base_url) != "https://api.openai.com/v1":
        raise HTTPException(503, "The support probe requires the official OpenAI endpoint.")
    today = utc_now().date()
    catalog = {
        key: price for key, price in pricing_catalog().items()
        if key.startswith("openai:") and price.effective_date is not None and price.effective_date <= today
        and config.llm_api_key.get_secret_value() not in price.source
    }
    model = config.llm_model
    if config.llm_api_key.get_secret_value() in model:
        raise HTTPException(503, "The configured OpenAI model is invalid.")
    requested_pricing = catalog.get(f"openai:{model}")
    if requested_pricing is None:
        raise HTTPException(503, "Configure dated USD pricing for the requested OpenAI model.")

    rate_snapshot = {"requested_pricing": requested_pricing.model_dump(mode="json")}

    # Commit an attempt reservation before the external call. A crash or concurrent retry cannot resend it.
    telemetry = Telemetry(model=model, provider="openai")
    initial = ExecutionInput(external_run_id=str(attempt_id), units=1, reviewed_units=0, reworked_units=0,
                             succeeded=False, data_origin="synthetic", model=model)
    try:
        row = save_execution(db, deployment, initial)
        row.telemetry = row.telemetry | {"provider_evidence": evidence(telemetry, model, "pending") | rate_snapshot}
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = replay(db, deployment_id, attempt_id)
        if existing is None:
            raise
        return existing

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Classify this fictional support ticket into one category. Return only the structured category."},
            {"role": "user", "content": TICKET},
        ],
        "max_completion_tokens": LIMIT,
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "synthetic_support_classification", "strict": True, "schema": Classification.model_json_schema(),
        }},
    }
    error = category = None
    try:
        content = request_completion(payload, config.model_copy(update={"extraction_provider": "openai"}), telemetry, catalog)
        category = Classification.model_validate_json(content).category
        if category != "account_access":
            error = "unexpected_classification"
    except ProviderError as exc:
        error = exc.code
    except ValidationError:
        error = "invalid_provider_output"

    final = ExecutionInput(
        external_run_id=str(attempt_id), occurred_at=initial.occurred_at, units=1, reviewed_units=0, reworked_units=0,
        succeeded=error is None, data_origin="synthetic", model_invoked=True, model=telemetry.model,
        input_tokens=telemetry.input_tokens, output_tokens=telemetry.output_tokens,
        latency_ms=telemetry.model_latency_ms, estimated_model_usd=telemetry.estimated_cost_usd,
        estimated_model_evidence=telemetry.pricing["source"] if telemetry.estimated_cost_usd is not None else None,
    )
    row.telemetry = final.model_dump(mode="json", exclude={"external_run_id", "occurred_at", "outcomes"}) | {
        "provider_evidence": evidence(telemetry, model, "success" if error is None else "failure", error, category) | rate_snapshot,
    }
    db.commit()
    db.refresh(row)
    return row
