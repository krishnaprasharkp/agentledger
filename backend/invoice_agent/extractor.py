
import re
from decimal import Decimal, InvalidOperation

from invoice_agent.schemas import InvoiceData


class ExtractionError(ValueError):
    pass


def find_field(text: str, pattern: str) -> str:
    match = re.search(
        pattern,
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    if not match:
        raise ExtractionError(
            f"Missing field matching: {pattern}"
        )

    return match.group(1).strip()


def extract_invoice_data(text: str) -> InvoiceData:
    """
    Extract data from our controlled sample format.

    This is a baseline parser, not a general-purpose
    invoice extraction engine.
    """

    if not text.strip():
        raise ExtractionError("Invoice text is empty.")

    try:
        vendor = find_field(
            text,
            r"^Vendor\s*:\s*(.+)$",
        )

        invoice_number = find_field(
            text,
            r"^Invoice Number\s*:\s*(\S+)",
        )

        invoice_date = find_field(
            text,
            r"^Invoice Date\s*:\s*(\d{4}-\d{2}-\d{2})",
        )

        currency = find_field(
            text,
            r"^Currency\s*:\s*([A-Z]{3})\s*$",
        )

        subtotal = find_field(
            text,
            r"^Subtotal\s*:\s*([0-9,]+\.\d{2})\s*$",
        )

        tax = find_field(
            text,
            r"^Tax\s*:\s*([0-9,]+\.\d{2})\s*$",
        )

        total = find_field(
            text,
            r"^Total\s*:\s*([0-9,]+\.\d{2})\s*$",
        )

        return InvoiceData(
            vendor_name=vendor,
            invoice_number=invoice_number,
            invoice_date=invoice_date,
            currency=currency.upper(),
            subtotal=Decimal(
                subtotal.replace(",", "")
            ),
            tax_amount=Decimal(
                tax.replace(",", "")
            ),
            total_amount=Decimal(
                total.replace(",", "")
            ),
        )

    except (InvalidOperation, ValueError) as exc:
        raise ExtractionError(
            f"Invoice extraction failed: {exc}"
        ) from exc
