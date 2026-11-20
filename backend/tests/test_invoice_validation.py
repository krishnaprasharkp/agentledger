
from decimal import Decimal

from invoice_agent.schemas import InvoiceData
from invoice_agent.validator import validate_invoice


def make_invoice(total="11800.00"):
    return InvoiceData(
        vendor_name="ABC Technologies",
        invoice_number="INV-2026-001",
        invoice_date="2026-11-16",
        currency="INR",
        subtotal=Decimal("10000.00"),
        tax_amount=Decimal("1800.00"),
        total_amount=Decimal(total),
    )


def test_valid_invoice():
    result = validate_invoice(
        make_invoice("11800.00")
    )

    assert result.is_valid is True
    assert result.requires_human_review is False
    assert result.discrepancies == []


def test_incorrect_total():
    result = validate_invoice(
        make_invoice("12500.00")
    )

    assert result.is_valid is False
    assert result.requires_human_review is True
    assert len(result.discrepancies) == 1
    assert "700.00" in result.discrepancies[0]


def test_rounding_tolerance():
    result = validate_invoice(
        make_invoice("11800.01")
    )

    assert result.is_valid is True


def test_negative_total_rejected():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        make_invoice("-100.00")
