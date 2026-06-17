"""
Text extraction service.

Three extraction paths:
  - PDF text extraction (pdfplumber), for digital/text-based PDFs
  - OCR (pytesseract + Pillow), for images and scanned content
  - Mock extraction, used when DEMO_MODE=true or the document is a demo
    document - returns one of the canned sample texts from
    demo_documents.py, so the full pipeline works without Tesseract/poppler
    installed

Limitation (documented in README): scanned PDFs (no embedded text layer)
are not automatically rasterized and OCR'd - pdfplumber will return little
or no text for those, which this service reports as a low-confidence /
failed extraction. For scanned content, upload as an image (PNG/JPG)
instead so the OCR path is used.
"""

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Document, DocumentStatus, ExtractedText, ExtractionMethod, ExtractionStatus
from app.services.audit import log_event
from app.services.demo_documents import DEFAULT_SCENARIO, SCENARIO_NOTE_PREFIX, get_scenario_text

logger = logging.getLogger("doc_automation.text_extraction")


class ExtractionError(Exception):
    """Raised when text extraction fails for a reason worth recording
    (corrupt file, no text found, OCR error, etc.)."""


# ---------------------------------------------------------------------------
# Real extraction
# ---------------------------------------------------------------------------

def extract_pdf_text(file_path: str) -> tuple[str, float]:
    """Extract text from a digital PDF using pdfplumber.

    Returns (text, confidence). Confidence is 1.0 if any text was found,
    0.0 if the PDF appears to have no extractable text layer (likely scanned).
    Raises ExtractionError if the file can't be opened/parsed at all.
    """
    import pdfplumber

    try:
        pages_text: list[str] = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                pages_text.append(page_text)
    except Exception as exc:
        raise ExtractionError(f"Could not parse PDF: {exc}") from exc

    text = "\n".join(pages_text).strip()

    if not text:
        raise ExtractionError(
            "No text layer found in this PDF - it may be a scanned document. "
            "Upload it as an image (PNG/JPG) instead to use OCR."
        )

    return text, 1.0


def extract_image_text(file_path: str) -> tuple[str, float]:
    """Extract text from an image using pytesseract OCR.

    Returns (text, confidence) where confidence is the average word-level
    confidence reported by Tesseract, scaled to 0.0-1.0.
    Raises ExtractionError if OCR fails or finds no text.
    """
    import pytesseract
    from PIL import Image

    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

    try:
        image = Image.open(file_path)

        text = pytesseract.image_to_string(image).strip()

        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        confidences = [int(c) for c in data.get("conf", []) if c not in ("-1", -1)]
        avg_confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
    except Exception as exc:
        raise ExtractionError(f"OCR failed: {exc}") from exc

    if not text:
        raise ExtractionError("OCR completed but no text was detected in the image.")

    return text, avg_confidence


# ---------------------------------------------------------------------------
# Mock extraction
# ---------------------------------------------------------------------------

def _resolve_demo_scenario(document: Document) -> str:
    """Pick a demo scenario key for a document.

    - If document.notes contains 'demo_scenario:<key>', use that key.
    - Otherwise, map expected_document_type to a representative scenario.
    - Otherwise, fall back to DEFAULT_SCENARIO.
    """
    notes = document.notes or ""
    for line in notes.splitlines():
        line = line.strip()
        if line.startswith(SCENARIO_NOTE_PREFIX):
            return line[len(SCENARIO_NOTE_PREFIX):].strip()

    if document.expected_document_type:
        type_to_scenario = {
            "invoice": "invoice_clean",
            "receipt": "receipt",
            "purchase_order": "purchase_order",
            "contract": "contract",
        }
        value = getattr(document.expected_document_type, "value", document.expected_document_type)
        return type_to_scenario.get(value, DEFAULT_SCENARIO)

    return DEFAULT_SCENARIO


def mock_extract(document: Document) -> tuple[str, float]:
    """Return canned sample text for demo/testing. Always 'succeeds'."""
    scenario_key = _resolve_demo_scenario(document)
    return get_scenario_text(scenario_key), 1.0


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def extract_text(db: Session, document: Document) -> ExtractedText:
    """Run text extraction for a document and persist the result.

    Updates Document.status to TEXT_EXTRACTED on success or
    EXTRACTION_FAILED on failure, and writes an audit log entry either way.
    """
    use_mock = settings.demo_mode or document.is_demo

    method: ExtractionMethod
    text: str = ""
    confidence: Optional[float] = None
    error_message: Optional[str] = None
    status = ExtractionStatus.SUCCESS

    try:
        if use_mock:
            method = ExtractionMethod.MOCK
            text, confidence = mock_extract(document)
        elif document.file_type == "pdf":
            method = ExtractionMethod.PDF_TEXT
            text, confidence = extract_pdf_text(document.file_path)
        else:  # png, jpg, jpeg
            method = ExtractionMethod.OCR
            text, confidence = extract_image_text(document.file_path)

    except ExtractionError as exc:
        method = (
            ExtractionMethod.MOCK
            if use_mock
            else (ExtractionMethod.PDF_TEXT if document.file_type == "pdf" else ExtractionMethod.OCR)
        )
        status = ExtractionStatus.FAILED
        error_message = str(exc)
        confidence = 0.0
        text = ""

    existing = db.query(ExtractedText).filter(ExtractedText.document_id == document.id).first()
    if existing:
        record = existing
    else:
        record = ExtractedText(document_id=document.id)
        db.add(record)

    record.raw_text = text
    record.extraction_method = method
    record.extraction_status = status
    record.extraction_confidence = confidence
    record.error_message = error_message

    document.status = (
        DocumentStatus.TEXT_EXTRACTED if status == ExtractionStatus.SUCCESS else DocumentStatus.EXTRACTION_FAILED
    )

    db.commit()
    db.refresh(record)
    db.refresh(document)

    if status == ExtractionStatus.SUCCESS:
        log_event(
            db,
            event_type="text_extracted",
            message=f"Text extraction completed via {method.value} (confidence={confidence:.2f}).",
            document_id=document.id,
            details={"method": method.value, "confidence": confidence, "characters": len(text)},
        )
    else:
        log_event(
            db,
            event_type="extraction_failed",
            message=f"Text extraction failed via {method.value}: {error_message}",
            document_id=document.id,
            details={"method": method.value, "error": error_message},
        )

    return record
