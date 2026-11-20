from datetime import timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import AwareDatetime, BaseModel, Field, model_validator

from domain import Deployment, Workflow, utc_now
from portfolio import Db, ExecutionInput, Name, Number, get, ingest

router = APIRouter(prefix="/adapters/service-desk", tags=["IT service desk adapter"])


class TicketInput(BaseModel):
    ticket_run_id: Name
    opened_at: AwareDatetime
    resolved_at: AwareDatetime | None = None
    escalated: bool
    reopened: bool
    human_reviewed: bool
    data_origin: Literal["measured", "synthetic"] = "measured"
    model_charge_usd: Number | None = None
    infrastructure_charge_usd: Number | None = None
    agent_latency_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def dates(self):
        if self.resolved_at and not self.opened_at <= self.resolved_at <= utc_now() + timedelta(minutes=5):
            raise ValueError("Resolution must be after opening and no later than the current time.")
        if self.opened_at > utc_now() + timedelta(minutes=5):
            raise ValueError("Opening time cannot be in the future.")
        return self


@router.post("/deployments/{deployment_id}/tickets", status_code=201)
def record_ticket(deployment_id: UUID, payload: TicketInput, db: Db):
    deployment = get(db, Deployment, deployment_id)
    if deployment.adapter != "service_desk":
        raise HTTPException(422, "This deployment is not registered for the service desk adapter.")

    workflow = get(db, Workflow, deployment.workflow_id)
    outcomes = {"escalated": int(payload.escalated), "resolved": int(payload.resolved_at is not None)}
    if payload.resolved_at:
        elapsed = (payload.resolved_at - payload.opened_at).total_seconds()
        outcomes["resolution_minutes"] = round(elapsed / 60, 8)
    event = ExecutionInput(
        external_run_id=payload.ticket_run_id,
        occurred_at=payload.resolved_at or utc_now(),
        units=1,
        reviewed_units=int(payload.human_reviewed),
        reworked_units=int(payload.reopened),
        succeeded=payload.resolved_at is not None,
        latency_ms=payload.agent_latency_ms,
        model_charge_usd=payload.model_charge_usd,
        infrastructure_charge_usd=payload.infrastructure_charge_usd,
        data_origin=payload.data_origin,
        outcomes={key: value for key, value in outcomes.items() if key in workflow.outcome_metrics},
    )
    return ingest(deployment_id, event, db)
