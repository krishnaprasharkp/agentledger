from functools import lru_cache
from os import environ
from typing import Literal
from uuid import UUID

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, model_validator

load_dotenv()


class Settings(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)

    app_mode: Literal["local", "private", "public_demo"] = "local"
    support_live_probe_enabled: bool = False
    extraction_provider: str = Field(default="rules", pattern="^(rules|openai|compatible)$")
    llm_base_url: HttpUrl = HttpUrl("https://api.openai.com/v1")
    llm_model: str = Field(default="gpt-4o-mini", min_length=1, max_length=255)
    llm_api_key: SecretStr = SecretStr("")
    llm_usage_cost_is_usd: bool = False
    llm_timeout_seconds: float = Field(default=30, gt=0, le=120)
    workspace_api_key: SecretStr = SecretStr("")
    static_dir: str = ""
    invoice_deployment_id: UUID | None = None
    invoice_telemetry_origin: Literal["measured", "synthetic"] = "measured"

    @model_validator(mode="after")
    def validate_provider(self):
        if self.app_mode == "private" and not self.workspace_api_key.get_secret_value().strip():
            raise ValueError("Private mode requires WORKSPACE_API_KEY.")
        if self.app_mode == "public_demo" and (
            self.support_live_probe_enabled or self.extraction_provider != "rules"
            or self.llm_api_key.get_secret_value() or self.workspace_api_key.get_secret_value()
        ):
            raise ValueError("Public demo mode must not have provider or workspace credentials enabled.")
        if self.extraction_provider != "rules" and not self.llm_api_key.get_secret_value():
            raise ValueError("LLM_API_KEY is required for hosted extraction")
        if self.extraction_provider == "openai" and str(self.llm_base_url) != "https://api.openai.com/v1":
            raise ValueError("Use the compatible provider for custom gateway URLs")
        if any((self.llm_base_url.username, self.llm_base_url.password, self.llm_base_url.query, self.llm_base_url.fragment)):
            raise ValueError("LLM_BASE_URL must contain only scheme, host and path.")
        if self.llm_base_url.scheme != "https" and self.llm_base_url.host not in {
            "localhost", "127.0.0.1", "::1", "[::1]",
        }:
            raise ValueError("LLM_BASE_URL must use HTTPS outside loopback")
        return self


@lru_cache
def get_settings() -> Settings:
    values = {
        field: environ[field.upper()]
        for field in Settings.model_fields
        if field.upper() in environ and (field != "invoice_deployment_id" or environ[field.upper()])
    }
    return Settings.model_validate(values)
