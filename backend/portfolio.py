from datetime import timedelta, timezone
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import AwareDatetime, BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from domain import Analysis, Baseline, Deployment, Execution, Organization, Outcome, Workflow, utc_now
from economics_types import Range
from investment import add, analyze, calculate, interval

router = APIRouter(prefix="/portfolio", tags=["Enterprise AI economics"])
Db = Annotated[Session, Depends(get_db)]
Name = Annotated[str, Field(min_length=1, max_length=160, pattern=r"\S")]
Metric = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,79}$")]
Number = Annotated[Decimal, Field(ge=0, le=1_000_000_000_000, decimal_places=14)]
Evidence = Annotated[str, Field(min_length=1, max_length=500, pattern=r"\S")]
ZERO = Decimal(0)
SUPPORT_PROBE_ADAPTER = "customer_support_probe"



class OrganizationInput(BaseModel):
    name: Name


class WorkflowInput(BaseModel):
    name: Name
    department: Name
    unit: Annotated[str, Field(min_length=1, max_length=80)]
    benefit_pool: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,159}$")]
    outcome_metrics: list[Metric] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def reserve_counterfactual(self):
        if "counterfactual_manual_cost" in self.outcome_metrics:
            raise ValueError("The counterfactual manual cost metric name is reserved.")
        return self


class BaselineInput(BaseModel):
    name: Name
    evidence: Evidence
    manual_cost_usd_per_unit: Range
    outcome_per_unit: dict[Metric, Range] = Field(default_factory=dict, max_length=20)


class DeploymentInput(BaseModel):
    name: Name
    adapter: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")] = "generic"


class ExecutionInput(BaseModel):
    external_run_id: Name
    occurred_at: AwareDatetime = Field(default_factory=utc_now)
    units: int = Field(ge=1, le=1_000_000)
    reviewed_units: int = Field(ge=0, le=1_000_000)
    reworked_units: int = Field(ge=0, le=1_000_000)
    succeeded: bool
    data_origin: Literal["measured", "synthetic"] = "measured"
    latency_ms: int | None = Field(default=None, ge=0)
    model_invoked: bool | None = None
    model: str | None = Field(default=None, max_length=255)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    model_charge_usd: Number | None = None
    estimated_model_usd: Number | None = None
    infrastructure_charge_usd: Number | None = None
    estimated_model_evidence: Evidence | None = None
    outcomes: dict[Metric, Number] = Field(default_factory=dict, max_length=20)

    @model_validator(mode="after")
    def validate_counts(self):
        if max(self.reviewed_units, self.reworked_units) > self.units:
            raise ValueError("Review and rework counts must be within execution units.")
        if self.model_invoked is False and any(value is not None for value in (
            self.model_charge_usd, self.estimated_model_usd, self.input_tokens, self.output_tokens,
        )):
            raise ValueError("Executions without a model call cannot report model charges or usage.")
        if self.estimated_model_usd is not None and not self.estimated_model_evidence:
            raise ValueError("Estimated model costs require a pricing source.")
        if self.occurred_at > utc_now() + timedelta(minutes=5):
            raise ValueError("Execution time cannot be in the future.")
        return self


class Valuation(BaseModel):
    direction: Literal[-1, 1]
    usd_per_metric_unit: Range


class EconomicsInput(BaseModel):
    baseline_id: UUID
    evidence: Evidence
    implementation_usd: Range
    fixed_model_usd_monthly: Range
    fixed_infrastructure_usd_monthly: Range
    maintenance_usd_monthly: Range
    review_usd_per_unit: Range
    rework_usd_per_unit: Range
    outcome_valuation: dict[Metric, Valuation] = Field(default_factory=dict, max_length=20)


class ForecastInput(EconomicsInput):
    months: int = Field(ge=1, le=120)
    units_monthly: Range
    review_fraction: Range
    rework_fraction: Range
    model_usd_per_unit: Range
    infrastructure_usd_per_unit: Range
    expected_outcomes_per_unit: dict[Metric, Range] = Field(default_factory=dict, max_length=20)

    @model_validator(mode="after")
    def validate_fractions(self):
        if max(self.review_fraction.high, self.rework_fraction.high) > 1:
            raise ValueError("Review and rework fractions must be between 0 and 1.")
        return self


class ForecastPreview(ForecastInput):
    baseline_id: UUID | None = None
    baseline: BaselineInput


class AssessmentInput(EconomicsInput):
    deployment_id: UUID
    start: AwareDatetime
    end: AwareDatetime
    missing_model_usd_per_execution: Range | None = None
    missing_infrastructure_usd_per_execution: Range | None = None

    @model_validator(mode="after")
    def check_window(self):
        self.start = self.start.astimezone(timezone.utc)
        self.end = self.end.astimezone(timezone.utc)
        if not self.start < self.end <= utc_now() or self.end - self.start > timedelta(days=3660):
            raise ValueError("Use a past observation window of up to 3,660 days.")
        return self


class SharedItem(BaseModel):
    key: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,159}$")]
    evidence: Evidence
    kind: Annotated[str, Field(pattern=r"^(implementation|recurring_cost|recurring_benefit)$")]
    usd: Range


class RollupInput(BaseModel):
    analysis_ids: list[UUID] = Field(min_length=1, max_length=100)
    shared_items: list[SharedItem] = Field(default_factory=list, max_length=100)
    disjoint_attribution_confirmed: Literal[True]


def get(db, model, entity_id):
    entity = db.get(model, entity_id)
    if entity is None:
        raise HTTPException(404, "Record was not found.")
    return entity


def new(db, entity):
    db.add(entity)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "That record or attribution key already exists.") from exc
    db.refresh(entity)
    return entity


def save_execution(db, deployment, payload):
    event = Execution(
        deployment_id=deployment.id, external_run_id=payload.external_run_id, occurred_at=payload.occurred_at.astimezone(timezone.utc),
        telemetry=payload.model_dump(mode="json", exclude={"external_run_id", "occurred_at", "outcomes"}),
    )
    db.add(event)
    db.flush()
    db.add_all(Outcome(execution_id=event.id, metric=key, value=str(value)) for key, value in payload.outcomes.items())
    return event


def require_metrics(keys, valid):
    if set(keys) - set(valid):
        raise HTTPException(422, "Declare every outcome metric on the workflow before using it.")


@router.post("/organizations", status_code=201)
def create_organization(payload: OrganizationInput, db: Db):
    return new(db, Organization(name=payload.name.strip()))


@router.get("/organizations")
def organizations(db: Db):
    return list(db.scalars(select(Organization).order_by(Organization.name)))


@router.post("/organizations/{organization_id}/workflows", status_code=201)
def create_workflow(organization_id: UUID, payload: WorkflowInput, db: Db):
    get(db, Organization, organization_id)
    values = payload.model_dump()
    values["outcome_metrics"] = sorted(set(payload.outcome_metrics))
    return new(db, Workflow(organization_id=organization_id, **values))


@router.get("/organizations/{organization_id}/workflows")
def workflows(organization_id: UUID, db: Db):
    get(db, Organization, organization_id)
    return list(db.scalars(select(Workflow).where(Workflow.organization_id == organization_id).order_by(Workflow.name)))


@router.get("/workflows/{workflow_id}")
def workflow_detail(workflow_id: UUID, db: Db):
    workflow = get(db, Workflow, workflow_id)
    return {
        "workflow": workflow,
        "baselines": list(db.scalars(select(Baseline).where(Baseline.workflow_id == workflow_id))),
        "deployments": list(db.scalars(select(Deployment).where(Deployment.workflow_id == workflow_id))),
        "analyses": list(db.scalars(select(Analysis).where(Analysis.workflow_id == workflow_id)
                                     .order_by(Analysis.created_at.desc()).limit(30))),
    }


@router.post("/workflows/{workflow_id}/baselines", status_code=201)
def create_baseline(workflow_id: UUID, payload: BaselineInput, db: Db):
    workflow = get(db, Workflow, workflow_id)
    require_metrics(payload.outcome_per_unit, workflow.outcome_metrics)
    return new(db, Baseline(workflow_id=workflow_id, name=payload.name, evidence=payload.evidence,
                            assumptions=payload.model_dump(mode="json", exclude={"name", "evidence"})))


@router.post("/workflows/{workflow_id}/deployments", status_code=201)
def create_deployment(workflow_id: UUID, payload: DeploymentInput, db: Db):
    get(db, Workflow, workflow_id)
    return new(db, Deployment(workflow_id=workflow_id, **payload.model_dump()))


@router.post("/deployments/{deployment_id}/executions", status_code=201)
def ingest(deployment_id: UUID, payload: ExecutionInput, db: Db):
    deployment = get(db, Deployment, deployment_id)
    if deployment.adapter == SUPPORT_PROBE_ADAPTER:
        raise HTTPException(422, "Provider probe evidence must be generated by the probe endpoint.")
    workflow = get(db, Workflow, deployment.workflow_id)
    require_metrics(payload.outcomes, workflow.outcome_metrics)
    try:
        event = save_execution(db, deployment, payload)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "The deployment already recorded this external run.") from exc
    db.refresh(event)
    return event


@router.get("/deployments/{deployment_id}/executions")
def recent_execution(deployment_id: UUID, db: Db):
    get(db, Deployment, deployment_id)
    rows = list(db.scalars(select(Execution).where(Execution.deployment_id == deployment_id)
                           .order_by(Execution.occurred_at.desc()).limit(25)))
    outcomes = {}
    for outcome in db.scalars(select(Outcome).where(Outcome.execution_id.in_([row.id for row in rows]))):
        outcomes.setdefault(outcome.execution_id, {})[outcome.metric] = outcome.value
    return [{"execution": row, "outcomes": outcomes.get(row.id, {})} for row in rows]


def observed(db, payload):
    rows = list(db.scalars(select(Execution).where(
        Execution.deployment_id == payload.deployment_id, Execution.occurred_at >= payload.start,
        Execution.occurred_at < payload.end,
    ).limit(10_001)))
    if not rows:
        raise HTTPException(422, "The assessment window contains no deployment executions.")
    if len(rows) > 10_000:
        raise HTTPException(422, "Use an assessment window with at most 10,000 executions.")
    values = {
        "executions": len(rows), "units": 0, "reviewed_units": 0, "reworked_units": 0,
        "successful_executions": 0, "model_charge_usd": ZERO, "estimated_model_usd": ZERO,
        "infrastructure_charge_usd": ZERO, "missing_model": 0, "missing_infrastructure": 0,
        "no_model_call_runs": 0, "model_charge_runs": 0, "estimated_model_runs": 0, "infrastructure_charge_runs": 0,
        "outcomes": {}, "outcome_covered_units": {},
        "data_origin": None, "input_tokens": 0, "output_tokens": 0, "usage_runs": 0,
    }
    units_by_id = {}
    for row in rows:
        data = row.telemetry
        origin = data.get("data_origin", "measured")
        if values["data_origin"] not in (None, origin):
            raise HTTPException(422, "Use separate deployments or windows for synthetic and measured runs.")
        values["data_origin"] = origin
        if data["input_tokens"] is not None and data["output_tokens"] is not None:
            values["usage_runs"] += 1
            values["input_tokens"] += data["input_tokens"]
            values["output_tokens"] += data["output_tokens"]
        units_by_id[row.id] = data["units"]
        for key in ("units", "reviewed_units", "reworked_units"):
            values[key] += data[key]
        values["successful_executions"] += data["succeeded"]
        if data.get("model_invoked") is False:
            values["no_model_call_runs"] += 1
        elif data["model_charge_usd"] is not None:
            values["model_charge_usd"] += Decimal(data["model_charge_usd"])
            values["model_charge_runs"] += 1
        elif data["estimated_model_usd"] is not None:
            values["estimated_model_usd"] += Decimal(data["estimated_model_usd"])
            values["estimated_model_runs"] += 1
        else:
            values["missing_model"] += 1
        if data["infrastructure_charge_usd"] is None:
            values["missing_infrastructure"] += 1
        else:
            values["infrastructure_charge_usd"] += Decimal(data["infrastructure_charge_usd"])
            values["infrastructure_charge_runs"] += 1
    for offset in range(0, len(rows), 500):
        ids = [row.id for row in rows[offset:offset + 500]]
        for item in db.scalars(select(Outcome).where(Outcome.execution_id.in_(ids))):
            values["outcomes"][item.metric] = values["outcomes"].get(item.metric, ZERO) + Decimal(item.value)
            values["outcome_covered_units"][item.metric] = (
                values["outcome_covered_units"].get(item.metric, 0) + units_by_id[item.execution_id]
            )
    return values


def run_analysis(db, workflow_id, payload, mode):
    workflow = get(db, Workflow, workflow_id)
    baseline = get(db, Baseline, payload.baseline_id)
    if baseline.workflow_id != workflow_id:
        raise HTTPException(422, "The baseline belongs to a different workflow.")
    require_metrics(payload.outcome_valuation, workflow.outcome_metrics)
    deployment_id = None
    metrics = None
    if mode == "assessment":
        deployment_id = payload.deployment_id
        deployment = get(db, Deployment, deployment_id)
        if deployment.workflow_id != workflow_id:
            raise HTTPException(422, "The deployment belongs to a different workflow.")
        if deployment.adapter == SUPPORT_PROBE_ADAPTER:
            raise HTTPException(422, "Synthetic provider probes are excluded from business ROI assessments.")
        metrics = observed(db, payload)
    else:
        require_metrics(payload.expected_outcomes_per_unit, workflow.outcome_metrics)
    results = analyze(payload, baseline, metrics)
    prior_estimates = None
    if metrics is not None:
        prior_estimates = {key: metrics.pop(key) for key in ("estimated_model_usd", "estimated_model_runs")}
    snapshot = {
        "schema_version": 1,
        "prior_estimates": prior_estimates,
        "measured": metrics,
        "assumptions": payload.model_dump(mode="json"),
        "baseline": {"name": baseline.name, "evidence": baseline.evidence, **baseline.assumptions},
        "estimates": results,
    }
    return new(db, Analysis(workflow_id=workflow_id, baseline_id=baseline.id, deployment_id=deployment_id,
                            mode=mode, snapshot=jsonable_encoder(snapshot, custom_encoder={Decimal: str})))


@router.post("/workflows/{workflow_id}/forecasts", status_code=201)
def forecast(workflow_id: UUID, payload: ForecastInput, db: Db):
    return run_analysis(db, workflow_id, payload, "forecast")


@router.post("/forecasts/preview")
def preview_forecast(payload: ForecastPreview):
    """Run the same forecasting calculation without creating portfolio records."""
    baseline = Baseline(assumptions=payload.baseline.model_dump(
        mode="json", exclude={"name", "evidence"},
    ))
    return {"estimates": analyze(payload, baseline)}


@router.post("/workflows/{workflow_id}/assessments", status_code=201)
def assess(workflow_id: UUID, payload: AssessmentInput, db: Db):
    return run_analysis(db, workflow_id, payload, "assessment")


@router.post("/organizations/{organization_id}/rollup")
def rollup(organization_id: UUID, payload: RollupInput, db: Db):
    get(db, Organization, organization_id)
    analyses = [get(db, Analysis, key) for key in payload.analysis_ids]
    selected = [get(db, Workflow, item.workflow_id) for item in analyses]
    if any(workflow.organization_id != organization_id for workflow in selected):
        raise HTTPException(422, "All selected analyses must belong to the organization.")
    if len({workflow.id for workflow in selected}) != len(analyses):
        raise HTTPException(422, "Select only one analysis per workflow.")
    first = analyses[0]
    mode = first.mode
    window_fields = ("months",) if mode == "forecast" else ("start", "end")
    window = {key: first.snapshot["assumptions"][key] for key in window_fields}
    if any(item.mode != mode or any(item.snapshot["assumptions"].get(key) != value for key, value in window.items())
           for item in analyses):
        raise HTTPException(422, "Select analyses with the same mode and reporting window.")
    if mode == "assessment" and len({item.snapshot["measured"]["data_origin"] for item in analyses}) > 1:
        raise HTTPException(422, "Roll up synthetic and measured assessments separately.")
    keys = [item.key for item in payload.shared_items]
    reserved = {workflow.benefit_pool for workflow in db.scalars(select(Workflow).where(
        Workflow.organization_id == organization_id,
    ))}
    if len(set(keys)) != len(keys) or reserved.intersection(keys):
        raise HTTPException(422, "Use a unique attribution key for each shared item, separate from workflow benefit pools.")
    costs = {key: [] for key in ("implementation", "recurring_cost", "recurring_benefit")}
    for item in analyses:
        result = item.snapshot["estimates"]
        for kind, key in (("implementation", "implementation_usd"), ("recurring_cost", "period_operating_usd"),
                          ("recurring_benefit", "period_benefit_usd")):
            costs[kind].append(interval(result[key]))
    for item in payload.shared_items:
        costs[item.kind].append(interval(item.usd))
    months = Decimal(first.snapshot["estimates"]["months"])
    return {
        "mode": mode, "window": window, "analysis_ids": payload.analysis_ids,
        "workflow_benefit_pools": sorted(workflow.benefit_pool for workflow in selected),
        "shared_items": payload.shared_items,
        "estimates": calculate(add(*costs["implementation"]), add(*costs["recurring_benefit"]), add(*costs["recurring_cost"]), months),
    }
