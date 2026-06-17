"""
Audit logging helper.

Every meaningful event in the document lifecycle should be written here,
so the audit log can always answer: what happened, when, and why?

event_type examples: "document_uploaded", "text_extracted",
"extraction_failed", "document_classified", "fields_extracted",
"validation_completed", "field_edited", "document_approved",
"document_rejected", "export_completed", "export_failed".
"""

from typing import Optional, Any

from sqlalchemy.orm import Session

from app.models import AuditLog


def log_event(
    db: Session,
    event_type: str,
    message: str,
    document_id: Optional[int] = None,
    details: Optional[Any] = None,
    actor: str = "system",
    commit: bool = True,
) -> AuditLog:
    """Create and persist a single audit log entry."""
    entry = AuditLog(
        document_id=document_id,
        event_type=event_type,
        message=message,
        details=details,
        actor=actor,
    )
    db.add(entry)
    if commit:
        db.commit()
        db.refresh(entry)
    return entry
