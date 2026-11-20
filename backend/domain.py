from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


def utc_now():
    return datetime.now(timezone.utc)


class Entity:
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)


class Organization(Entity, Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(160), unique=True)


class Workflow(Entity, Base):
    __tablename__ = "workflows"
    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        UniqueConstraint("organization_id", "benefit_pool"),
    )
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    department: Mapped[str] = mapped_column(String(160))
    unit: Mapped[str] = mapped_column(String(80))
    benefit_pool: Mapped[str] = mapped_column(String(160))
    outcome_metrics: Mapped[list] = mapped_column(JSON)


class Baseline(Entity, Base):
    __tablename__ = "baseline_scenarios"
    workflow_id: Mapped[UUID] = mapped_column(ForeignKey("workflows.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    evidence: Mapped[str] = mapped_column(String(500))
    assumptions: Mapped[dict] = mapped_column(JSON)


class Deployment(Entity, Base):
    __tablename__ = "ai_deployments"
    workflow_id: Mapped[UUID] = mapped_column(ForeignKey("workflows.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    adapter: Mapped[str] = mapped_column(String(40))


class Execution(Entity, Base):
    __tablename__ = "workflow_executions"
    __table_args__ = (
        UniqueConstraint("deployment_id", "external_run_id"),
        Index("ix_workflow_executions_deployment_time", "deployment_id", "occurred_at"),
    )
    deployment_id: Mapped[UUID] = mapped_column(ForeignKey("ai_deployments.id"))
    external_run_id: Mapped[str] = mapped_column(String(160))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    telemetry: Mapped[dict] = mapped_column(JSON)


class Outcome(Entity, Base):
    __tablename__ = "business_outcomes"
    __table_args__ = (UniqueConstraint("execution_id", "metric"),)
    execution_id: Mapped[UUID] = mapped_column(ForeignKey("workflow_executions.id"))
    metric: Mapped[str] = mapped_column(String(80))
    value: Mapped[str] = mapped_column(String(80))


class Analysis(Entity, Base):
    __tablename__ = "roi_analyses"
    workflow_id: Mapped[UUID] = mapped_column(ForeignKey("workflows.id"), index=True)
    baseline_id: Mapped[UUID] = mapped_column(ForeignKey("baseline_scenarios.id"))
    deployment_id: Mapped[UUID | None] = mapped_column(ForeignKey("ai_deployments.id"))
    mode: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    snapshot: Mapped[dict] = mapped_column(JSON)
