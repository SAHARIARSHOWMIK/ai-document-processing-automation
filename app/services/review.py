"""
Review and approval service.

This is the human-in-the-loop gate for the document pipeline:

    AI recommends. Validation checks. Human approves. System exports.

Approval rules enforced here (from the project spec):
  1. Documents with validation errors (status='failed') cannot be approved
     until corrected (edit fields, which re-runs validation).
  2. Documents with warnings/requires_review can be approved after review.
  3. Rejected documents are terminal - cannot be approved or exported later.
  4. Only approved documents can be exported (enforced in the export service).
  5. Edited fields are recorded on the Approval record (old -> new).
  6. Approval/rejection decisions are written to the audit log.

Valid document.status transitions handled here:
    pending_review | needs_correction  --edit fields-->  pending_review (re-validated)
    pending_review | needs_correction  --approve-->      approved
    pending_review | needs_correction  --reject-->       rejected
    pending_review                     --needs_correction--> needs_correction

approved/rejected/exported are terminal for review actions.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models import (
    Approval,
    ApprovalStatus,
    Document,
    DocumentStatus,
    ExtractedData,
    ValidationResult,
    ValidationStatus,
)
from app.schemas import DOCUMENT_FIELD_SCHEMAS
from app.services.audit import log_event
from app.services.validation_engine import run_validation

_EDITABLE_STATUSES = {DocumentStatus.EXTRACTED, DocumentStatus.VALIDATED, DocumentStatus.PENDING_REVIEW, DocumentStatus.NEEDS_CORRECTION}
_DECIDABLE_STATUSES = {DocumentStatus.PENDING_REVIEW, DocumentStatus.NEEDS_CORRECTION}


class ApprovalError(Exception):
    """Raised when a review-workflow transition is not allowed."""


def get_or_create_approval(db: Session, document: Document) -> Approval:
    approval = document.approval
    if approval:
        return approval

    approval = Approval(document_id=document.id, status=ApprovalStatus.PENDING)
    db.add(approval)
    db.commit()
    db.refresh(approval)
    return approval


def edit_fields(db: Session, document: Document, new_fields: dict) -> tuple[ExtractedData, ValidationResult]:
    """Edit a document's extracted fields before approval.

    Validates `new_fields` against the per-type schema (lenient - unknown
    keys are dropped), records the diff (old -> new) on the Approval record,
    re-runs validation, and sets document.status back to 'pending_review'.

    Raises ApprovalError if the document is not in an editable state
    (must be 'pending_review' or 'needs_correction').
    """
    if document.status not in _EDITABLE_STATUSES:
        raise ApprovalError(
            f"Document {document.id} cannot be edited from status '{document.status.value}'. "
            f"Only documents with status 'extracted', 'validated', 'pending_review', or 'needs_correction' can be edited."
        )

    extracted_data = document.extracted_data
    if not extracted_data:
        raise ApprovalError(f"Document {document.id} has no extracted data to edit.")

    schema_cls = DOCUMENT_FIELD_SCHEMAS.get(extracted_data.document_type)
    if schema_cls:
        validated = schema_cls.model_validate(new_fields)
        normalized_fields = validated.model_dump()
    else:
        normalized_fields = new_fields

    old_fields = extracted_data.extracted_fields or {}

    diff: dict = {}
    all_keys = set(old_fields.keys()) | set(normalized_fields.keys())
    for key in all_keys:
        old_value = old_fields.get(key)
        new_value = normalized_fields.get(key)
        if old_value != new_value:
            diff[key] = {"old": old_value, "new": new_value}

    extracted_data.extracted_fields = normalized_fields
    db.commit()
    db.refresh(extracted_data)

    if diff:
        approval = get_or_create_approval(db, document)
        existing_diff = approval.edited_fields or {}
        existing_diff.update(diff)
        approval.edited_fields = existing_diff
        db.commit()
        db.refresh(approval)

        log_event(
            db,
            event_type="field_edited",
            message=f"User corrected {len(diff)} field(s): {', '.join(diff.keys())}.",
            document_id=document.id,
            details={"diff": diff},
            actor="user",
        )

    validation_result = run_validation(db, document)
    db.refresh(document)

    return extracted_data, validation_result


def approve_document(db: Session, document: Document, reviewer_note: Optional[str] = None) -> Approval:
    """Approve a document for export.

    Raises ApprovalError if:
      - document.status is not 'pending_review' or 'needs_correction'
      - the latest validation result has status 'failed' (errors must be
        fixed via edit_fields first, which re-runs validation)
    """
    if document.status not in _DECIDABLE_STATUSES:
        raise ApprovalError(
            f"Document {document.id} cannot be approved from status '{document.status.value}'. "
            f"Only documents with status 'pending_review' or 'needs_correction' can be approved."
        )

    validation_result = document.validation_result
    if validation_result and validation_result.status == ValidationStatus.FAILED:
        raise ApprovalError(
            f"Document {document.id} has validation errors and cannot be approved. "
            f"Correct the flagged fields (PATCH /documents/{document.id}/fields) and try again."
        )

    approval = get_or_create_approval(db, document)
    approval.status = ApprovalStatus.APPROVED
    approval.decided_at = datetime.utcnow()
    approval.reviewer_note = reviewer_note
    approval.final_data = (document.extracted_data.extracted_fields or {}) if document.extracted_data else {}

    document.status = DocumentStatus.APPROVED

    db.commit()
    db.refresh(approval)
    db.refresh(document)

    log_event(
        db,
        event_type="document_approved",
        message="Reviewer approved document." + (f" Note: {reviewer_note}" if reviewer_note else ""),
        document_id=document.id,
        actor="user",
    )

    return approval


def reject_document(db: Session, document: Document, reviewer_note: Optional[str] = None) -> Approval:
    """Reject a document. Rejected documents are terminal and cannot be exported."""
    if document.status not in _DECIDABLE_STATUSES:
        raise ApprovalError(
            f"Document {document.id} cannot be rejected from status '{document.status.value}'. "
            f"Only documents with status 'pending_review' or 'needs_correction' can be rejected."
        )

    approval = get_or_create_approval(db, document)
    approval.status = ApprovalStatus.REJECTED
    approval.decided_at = datetime.utcnow()
    approval.reviewer_note = reviewer_note

    document.status = DocumentStatus.REJECTED

    db.commit()
    db.refresh(approval)
    db.refresh(document)

    log_event(
        db,
        event_type="document_rejected",
        message="Reviewer rejected document." + (f" Note: {reviewer_note}" if reviewer_note else ""),
        document_id=document.id,
        actor="user",
    )

    return approval


def request_correction(db: Session, document: Document, reviewer_note: Optional[str] = None) -> Approval:
    """Send a document back for correction (status -> 'needs_correction').

    The reviewer can then use PATCH /documents/{id}/fields to fix issues,
    which automatically returns the document to 'pending_review'.
    """
    if document.status != DocumentStatus.PENDING_REVIEW:
        raise ApprovalError(
            f"Document {document.id} cannot be sent for correction from status '{document.status.value}'. "
            f"Only documents with status 'pending_review' can be sent for correction."
        )

    approval = get_or_create_approval(db, document)
    approval.status = ApprovalStatus.NEEDS_CORRECTION
    approval.reviewer_note = reviewer_note

    document.status = DocumentStatus.NEEDS_CORRECTION

    db.commit()
    db.refresh(approval)
    db.refresh(document)

    log_event(
        db,
        event_type="needs_correction_requested",
        message="Reviewer requested corrections before this document can be approved."
        + (f" Note: {reviewer_note}" if reviewer_note else ""),
        document_id=document.id,
        actor="user",
    )

    return approval
