
import pymupdf

sample_text = """
INVOICE

Vendor: ABC Technologies
Invoice Number: INV-2026-001
Invoice Date: 2026-11-16
Currency: INR

Subtotal: 10000.00
Tax: 1800.00
Total: 12500.00
"""

document = pymupdf.open()

page = document.new_page()

page.insert_text(
    (72, 72),
    sample_text,
    fontsize=12,
)

document.save("sample_invoice.pdf")
document.close()

print("Sample invoice PDF created successfully.")
