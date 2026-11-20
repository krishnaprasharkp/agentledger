
import io

import pymupdf





def test_pdf_invoice_pipeline(client):
    document = pymupdf.open()
    page = document.new_page()

    page.insert_text(
        (72, 72),
        (
            "Vendor: ABC Technologies\n"
            "Invoice Number: INV-2026-001\n"
            "Invoice Date: 2026-11-16\n"
            "Currency: INR\n"
            "Subtotal: 10000.00\n"
            "Tax: 1800.00\n"
            "Total: 12500.00"
        ),
    )

    pdf_bytes = document.tobytes()
    document.close()

    response = client.post(
        "/invoices/process",
        files={
            "file": (
                "invoice.pdf",
                io.BytesIO(pdf_bytes),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 200

    result = response.json()

    assert (
        result["invoice"]["invoice_number"]
        == "INV-2026-001"
    )

    assert result["validation"]["is_valid"] is False

    assert (
        result["validation"]["requires_human_review"]
        is True
    )
