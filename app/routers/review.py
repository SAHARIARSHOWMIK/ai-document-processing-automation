"""
Review and approval endpoints:
  PATCH /documents/{id}/fields           - edit extracted fields before approval
  POST  /documents/{id}/approve          - approve a document for export
  POST  /documents/{id}/reject           - reject a document
  POST  /documents/{id}/request-correction - send back for correction
  GET   /documents/{id}/approval         - get the approval record
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Approval, Document
from app.schemas import (
    ApprovalOut,
    FieldEditRequest,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
)
from app.services.review import (
    ApprovalError,
    approve_document,
    edit_fields,
    reject_document,
    request_correction,
)

router = APIRouter(prefix="/documents", tags=["review"])


def _get_document_or_404(db: Session, document_id: int) -> Document:
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.patch("/{document_id}/fields", response_model=ReviewDecisionResponse)
def patch_fields(document_id: int, body: FieldEditRequest, db: Session = Depends(get_db)):
    """Correct extracted fields before approval.

    Accepts the full corrected `extracted_fields` dict for this document's
    type. The diff (old -> new) is recorded on the approval record, and
    validation is automatically re-run - so a document with validation
    errors can be fixed here and then re-checked before approval.

    Only documents with status 'pending_review' or 'needs_correction' can
    be edited.
    """
    document = _get_document_or_404(db, document_id)

    try:
        edit_fields(db, document, body.fields)
    except ApprovalError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    db.refresh(document)
    approval = document.approval

    return ReviewDecisionResponse(
        document=document,
        approval=approval,
        message="Fields updated and validation re-run.",
    )


@router.post("/{document_id}/approve", response_model=ReviewDecisionResponse)
def approve(document_id: int, body: ReviewDecisionRequest = ReviewDecisionRequest(), db: Session = Depends(get_db)):
    """Approve a document, making it eligible for export.

    Blocked if the latest validation result has status 'failed' - errors
    must be corrected first via PATCH /documents/{id}/fields.
    """
    document = _get_document_or_404(db, document_id)

    try:
        approval = approve_document(db, document, reviewer_note=body.reviewer_note)
    except ApprovalError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    db.refresh(document)
    return ReviewDecisionResponse(document=document, approval=approval, message="Document approved.")


@router.post("/{document_id}/reject", response_model=ReviewDecisionResponse)
def reject(document_id: int, body: ReviewDecisionRequest = ReviewDecisionRequest(), db: Session = Depends(get_db)):
    """Reject a document. Rejected documents are terminal and can never be exported."""
    document = _get_document_or_404(db, document_id)

    try:
        approval = reject_document(db, document, reviewer_note=body.reviewer_note)
    except ApprovalError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    db.refresh(document)
    return ReviewDecisionResponse(document=document, approval=approval, message="Document rejected.")


@router.post("/{document_id}/request-correction", response_model=ReviewDecisionResponse)
def request_correction_endpoint(
    document_id: int, body: ReviewDecisionRequest = ReviewDecisionRequest(), db: Session = Depends(get_db)
):
    """Send a document back for correction (status -> 'needs_correction').

    Use PATCH /documents/{id}/fields afterward to fix the flagged issues,
    which automatically returns the document to 'pending_review'.
    """
    document = _get_document_or_404(db, document_id)

    try:
        approval = request_correction(db, document, reviewer_note=body.reviewer_note)
    except ApprovalError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    db.refresh(document)
    return ReviewDecisionResponse(document=document, approval=approval, message="Sent back for correction.")


@router.get("/{document_id}/approval", response_model=ApprovalOut)
def get_approval(document_id: int, db: Session = Depends(get_db)):
    """Get the approval record for a document, if a review decision has been made."""
    approval = db.query(Approval).filter(Approval.document_id == document_id).first()
    if not approval:
        raise HTTPException(status_code=404, detail="No review decision has been made for this document yet")
    return approval
