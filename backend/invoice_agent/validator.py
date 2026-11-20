
from decimal import Decimal

from invoice_agent.schemas import (
    InvoiceData,
    InvoiceValidation,
)


def validate_invoice(
    invoice: InvoiceData,
) -> InvoiceValidation:
    discrepancies = []

    expected_total = (
        invoice.subtotal + invoice.tax_amount
    )

    difference = abs(
        expected_total - invoice.total_amount
    )

    tolerance = Decimal("0.01")

    if difference > tolerance:
        discrepancies.append(
            f"Total mismatch: expected "
            f"{expected_total}, "
            f"received {invoice.total_amount}. "
            f"Difference: {difference}"
        )

    is_valid = len(discrepancies) == 0

    return InvoiceValidation(
        is_valid=is_valid,
        discrepancies=discrepancies,
        requires_human_review=not is_valid,
    )
