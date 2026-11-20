from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, DateTime, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class AgentEventRecord(Base):
    __tablename__ = "agent_events"

    run_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )

    agent_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )

    model: Mapped[str] = mapped_column(
        String(255), nullable=False
    )

    input_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    output_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    latency_ms: Mapped[int] = mapped_column(
        Integer, nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(20), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    workflow: Mapped[str | None] = mapped_column(String(32))
    provider: Mapped[str | None] = mapped_column(String(32))
    model_latency_ms: Mapped[int | None] = mapped_column(Integer)
    usage_reported: Mapped[bool | None] = mapped_column(Boolean)
    provider_charge_usd: Mapped[Decimal | None] = mapped_column(Numeric(30, 14))
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(30, 14))
    pricing: Mapped[dict | None] = mapped_column(JSON)
    provider_request_id: Mapped[str | None] = mapped_column(String(255))
    validation_passed: Mapped[bool | None] = mapped_column(Boolean)
    requires_human_review: Mapped[bool | None] = mapped_column(Boolean)
    error_code: Mapped[str | None] = mapped_column(String(64))