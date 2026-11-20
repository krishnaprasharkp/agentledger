from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class Range(BaseModel):
    low: Decimal = Field(ge=0, le=1_000_000, decimal_places=8)
    high: Decimal = Field(ge=0, le=1_000_000, decimal_places=8)

    @model_validator(mode="after")
    def check_bounds(self):
        if self.low > self.high:
            raise ValueError("The low endpoint must be less than or equal to the high endpoint.")
        return self
