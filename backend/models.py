from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class AgentEventCreate(BaseModel):
    agent_id: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=255)
    input_tokens: int = Field(ge=0, le=2_147_483_647)
    output_tokens: int = Field(ge=0, le=2_147_483_647)
    latency_ms: int = Field(ge=0, le=2_147_483_647)
    status: str = Field(pattern="^(success|failure)$")


class AgentEvent(AgentEventCreate):
    model_config = ConfigDict(from_attributes=True)
    run_id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    workflow: str | None = None
    provider: str | None = None
    model_latency_ms: int | None = None
    usage_reported: bool | None = None
    provider_charge_usd: Decimal | None = None
    estimated_cost_usd: Decimal | None = None
    pricing: dict | None = None
    provider_request_id: str | None = None
    validation_passed: bool | None = None
    requires_human_review: bool | None = None
    error_code: str | None = None
