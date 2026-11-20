
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class InvoiceData(BaseModel):
    vendor_name: str = Field(min_length=1)
    invoice_number: str = Field(min_length=1)
    invoice_date: date
    currency: str = Field(min_length=3, max_length=3)
    subtotal: Decimal = Field(ge=0)
    tax_amount: Decimal = Field(ge=0)
    total_amount: Decimal = Field(ge=0)


class InvoiceValidation(BaseModel):
    is_valid: bool
    discrepancies: list[str]
    requires_human_review: bool
