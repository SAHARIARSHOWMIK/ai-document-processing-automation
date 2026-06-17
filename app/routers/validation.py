"""
Validation endpoints:
  POST /documents/{id}/validate   - run the validation engine and save the result
  GET  /documents/{id}/validation - retrieve the saved validation result
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, ValidationResult
from app.schemas import ValidationResultOut
from app.services.validation_engine import run_validation

router = APIRouter(prefix="/documents", tags=["validation"])


@router.post("/{document_id}/validate", response_model=ValidationResultOut)
def validate(document_id: int, db: Session = Depends(get_db)):
    """Run business-rule validation on a document's extracted fields.

    Requires field extraction to have completed (POST /documents/{id}/extract-fields).

    Produces a status of:
      - 'failed'           : one or more required fields are missing or
                              clearly invalid (e.g. negative amount, due date
                              before invoice date) - cannot be approved until fixed.
      - 'requires_review'  : overall AI extraction confidence was below the
                              review threshold.
      - 'warning'          : no errors, but issues like total mismatches,
                              high amounts, duplicates, or missing optional
                              fields were found - can be approved after review.
      - 'valid'            : no issues found.

    After validation, the document status becomes 'pending_review' and it
    appears in the human review queue regardless of validation status.

    Re-running this overwrites the previous validation result.
    """
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if not document.extracted_data:
        raise HTTPException(
            status_code=400,
            detail="This document has no extracted field data. Run POST /documents/{id}/extract-fields first.",
        )

    return run_validation(db, document)


@router.get("/{document_id}/validation", response_model=ValidationResultOut)
def get_validation(document_id: int, db: Session = Depends(get_db)):
    """Get the saved validation result for a document, if available."""
    record = db.query(ValidationResult).filter(ValidationResult.document_id == document_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="This document has not been validated yet")
    return record
