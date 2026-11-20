
import pymupdf


MAX_PDF_SIZE = 5 * 1024 * 1024
MAX_PAGES = 20


def extract_pdf_text(pdf_bytes: bytes) -> dict:
    if not pdf_bytes.startswith(b"%PDF-"):
        raise ValueError("File is not a valid PDF.")

    if len(pdf_bytes) > MAX_PDF_SIZE:
        raise ValueError("PDF exceeds 5 MB limit.")

    try:
        with pymupdf.open(
            stream=pdf_bytes, filetype="pdf"
        ) as document:
            if document.needs_pass:
                raise ValueError(
                    "Password-protected PDFs are not supported."
                )

            if document.page_count > MAX_PAGES:
                raise ValueError(
                    "PDF exceeds 20-page limit."
                )

            text = "\n".join(
                page.get_text("text")
                for page in document
            )

            return {
                "page_count": document.page_count,
                "character_count": len(text),
                "text": text,
            }

    except pymupdf.FileDataError as exc:
        raise ValueError(
            "Cannot read the uploaded PDF."
        ) from exc
