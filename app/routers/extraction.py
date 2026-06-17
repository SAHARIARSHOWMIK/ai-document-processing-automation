"""
Text extraction endpoints:
  POST /documents/{id}/extract        - run text extraction and save the result
  GET  /documents/{id}/extracted-text - retrieve the saved extraction result
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, ExtractedText
from app.schemas import ExtractedTextOut
from app.services.text_extraction import extract_text

router = APIRouter(prefix="/documents", tags=["extraction"])


@router.post("/{document_id}/extract", response_model=ExtractedTextOut)
def run_extraction(document_id: int, db: Session = Depends(get_db)):
    """Run text extraction for a document.

    - PDFs use pdfplumber (digital text layer required).
    - Images (PNG/JPG/JPEG) use Tesseract OCR.
    - In demo mode (or for demo documents), a canned sample text is returned
      instead, so the pipeline works without Tesseract/poppler installed.

    On success, Document.status becomes 'text_extracted'. On failure
    (e.g. scanned PDF with no text layer, or OCR finding nothing),
    Document.status becomes 'extraction_failed' and the error is recorded -
    this endpoint does not raise an HTTP error in that case, so the caller
    can inspect `extraction_status` and `error_message`.

    Re-running this overwrites the previous extraction result.
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    return extract_text(db, document)


@router.get("/{document_id}/extracted-text", response_model=ExtractedTextOut)
def get_extracted_text(document_id: int, db: Session = Depends(get_db)):
    """Get the saved text extraction result for a document, if it has been run."""
    record = db.query(ExtractedText).filter(ExtractedText.document_id == document_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="This document has not been processed yet")
    return record
