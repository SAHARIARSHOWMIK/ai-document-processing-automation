"""
AI document analysis endpoints:
  POST /documents/{id}/classify       - classify the document type
  POST /documents/{id}/extract-fields - extract structured fields for the
                                         classified document type
  GET  /documents/{id}/extracted-data - retrieve saved extraction result
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Document, DocumentStatus, DocumentType, ExtractedData, ExtractionStatus
from app.schemas import DocumentOut, ExtractedDataOut
from app.services.ai_document import classify_document, extract_fields
from app.services.audit import log_event

router = APIRouter(prefix="/documents", tags=["ai"])


@router.post("/{document_id}/classify", response_model=DocumentOut)
def classify(document_id: int, db: Session = Depends(get_db)):
    """Classify the document type from its extracted text.

    Requires text extraction to have completed successfully first
    (run POST /documents/{id}/extract).

    Confidence rules:
      - >= CLASSIFICATION_AUTO_THRESHOLD (default 0.80): status -> 'classified',
        ready for automatic field extraction.
      - CLASSIFICATION_REVIEW_THRESHOLD to AUTO_THRESHOLD (default 0.60-0.79):
        status -> 'classified', but a low-confidence audit warning is logged
        so it's flagged for review.
      - below REVIEW_THRESHOLD, or document_type == 'unknown': status ->
        'pending_review' - field extraction will not run automatically.

    Re-running this overwrites the previous classification.
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not document.extracted_text or document.extracted_text.extraction_status != ExtractionStatus.SUCCESS:
        raise HTTPException(
            status_code=400,
            detail="This document has no successful text extraction yet. Run POST /documents/{id}/extract first.",
        )

    result, raw_response = classify_document(document.extracted_text.raw_text)

    document.document_type = result.document_type
    document.classification_confidence = result.confidence
    document.classification_reason = result.reason

    if result.document_type == DocumentType.UNKNOWN or result.confidence < settings.classification_review_threshold:
        document.status = DocumentStatus.PENDING_REVIEW
    else:
        document.status = DocumentStatus.CLASSIFIED

    db.commit()
    db.refresh(document)

    log_event(
        db,
        event_type="document_classified",
        message=(
            f"Classified as {result.document_type.value} "
            f"(confidence={result.confidence:.2f}): {result.reason}"
        ),
        document_id=document.id,
        details={"mode": raw_response.get("mode"), "confidence": result.confidence},
    )

    if result.document_type != DocumentType.UNKNOWN and (
        settings.classification_review_threshold <= result.confidence < settings.classification_auto_threshold
    ):
        log_event(
            db,
            event_type="low_confidence_classification",
            message=(
                f"Classification confidence ({result.confidence:.2f}) is below the "
                f"auto-proceed threshold ({settings.classification_auto_threshold:.2f}) - "
                f"flagged for review."
            ),
            document_id=document.id,
        )

    if document.status == DocumentStatus.PENDING_REVIEW:
        log_event(
            db,
            event_type="manual_review_required",
            message=(
                f"Classification confidence ({result.confidence:.2f}) is below the review "
                f"threshold ({settings.classification_review_threshold:.2f}) or the document "
                f"type is unknown - sent to manual review. Field extraction will not run "
                f"automatically."
            ),
            document_id=document.id,
        )

    return document


@router.post("/{document_id}/extract-fields", response_model=ExtractedDataOut)
def run_field_extraction(
    document_id: int,
    force: bool = Query(False, description="Run extraction even if the document is pending manual review"),
    db: Session = Depends(get_db),
):
    """Extract structured fields for a classified document.

    Requires the document to have been classified (POST /documents/{id}/classify)
    with a document_type other than 'unknown'. If the document is in
    'pending_review' (low classification confidence), this is blocked unless
    `force=true` is passed - matching the rule that low-confidence/unknown
    documents are not extracted automatically.

    Re-running this overwrites the previous extraction result.
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not document.document_type or document.document_type == DocumentType.UNKNOWN:
        raise HTTPException(
            status_code=400,
            detail="This document has not been classified (or was classified as 'unknown'). "
            "Run POST /documents/{id}/classify first.",
        )

    if not document.extracted_text or document.extracted_text.extraction_status != ExtractionStatus.SUCCESS:
        raise HTTPException(
            status_code=400,
            detail="This document has no successful text extraction. Run POST /documents/{id}/extract first.",
        )

    if document.status == DocumentStatus.PENDING_REVIEW and not force:
        raise HTTPException(
            status_code=400,
            detail=(
                "This document is pending manual review due to low classification "
                "confidence. Pass ?force=true to extract fields anyway, or correct "
                "the classification first."
            ),
        )

    result, raw_response = extract_fields(document.document_type, document.extracted_text.raw_text)

    existing = db.query(ExtractedData).filter(ExtractedData.document_id == document_id).first()
    if existing:
        record = existing
    else:
        record = ExtractedData(document_id=document_id)
        db.add(record)

    record.document_type = result.document_type
    record.extracted_fields = result.extracted_fields
    record.missing_fields = result.missing_fields
    record.uncertain_fields = result.uncertain_fields
    record.overall_confidence = result.confidence
    record.summary = result.summary
    record.raw_ai_response = raw_response

    document.status = DocumentStatus.EXTRACTED

    db.commit()
    db.refresh(record)
    db.refresh(document)

    log_event(
        db,
        event_type="fields_extracted",
        message=(
            f"Extracted {result.document_type.value} fields "
            f"(confidence={result.confidence:.2f}). "
            f"Missing: {result.missing_fields or 'none'}. "
            f"Uncertain: {result.uncertain_fields or 'none'}."
        ),
        document_id=document.id,
        details={"mode": raw_response.get("mode"), "confidence": result.confidence},
    )

    return record


@router.get("/{document_id}/extracted-data", response_model=ExtractedDataOut)
def get_extracted_data(document_id: int, db: Session = Depends(get_db)):
    """Get the saved field-extraction result for a document, if available."""
    record = db.query(ExtractedData).filter(ExtractedData.document_id == document_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="This document has not had fields extracted yet")
    return record
