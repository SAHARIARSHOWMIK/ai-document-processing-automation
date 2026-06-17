"""
Export service.

Enforces the core export rule from the spec:

    Only approved documents can be exported.

Supports CSV and JSON export of one or more approved documents. Exported
data comes from Approval.final_data (the human-confirmed data snapshotted
at approval time), not directly from ExtractedData - so if a document is
edited after being exported (re-approved), the export reflects what was
actually approved, not whatever the AI originally extracted.

Per-document-type export field sets (invoice, receipt, purchase_order,
contract) all share a common envelope:
    document_id, document_type, filename, approval_status, export_timestamp
plus the type-specific fields flattened on top (line_items/items are
JSON-encoded as a string for the CSV case, since CSV is flat).
"""

import csv
import json
import os
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Approval,
    ApprovalStatus,
    Document,
    DocumentStatus,
    ExportLog,
    ExportStatus,
    ExportType,
)
from app.services.audit import log_event


class ExportError(Exception):
    """Raised when a document cannot be exported (not approved, etc.)."""


def _document_export_row(document: Document) -> dict:
    """Build a flat dict of exportable fields for a single approved document."""
    approval: Optional[Approval] = document.approval
    final_data = (approval.final_data if approval else None) or {}

    row = {
        "document_id": document.id,
        "filename": document.filename,
        "document_type": document.document_type.value if document.document_type else None,
        "approval_status": approval.status.value if approval else None,
        "approved_at": approval.decided_at.isoformat() if approval and approval.decided_at else None,
    }

    for key, value in final_data.items():
        if isinstance(value, (list, dict)):
            row[key] = json.dumps(value)
        else:
            row[key] = value

    return row


def _assert_approved(document: Document) -> None:
    if document.status != DocumentStatus.APPROVED or not document.approval or document.approval.status != ApprovalStatus.APPROVED:
        raise ExportError(
            f"Document {document.id} is not approved (status='{document.status.value}'). "
            f"Only approved documents can be exported."
        )


def export_documents_csv(db: Session, document_ids: list[int]) -> ExportLog:
    """Export one or more approved documents to a single CSV file.

    Raises ExportError (and logs an export_failed audit event per offending
    document) if any requested document is not approved - no partial file
    is written in that case.
    """
    documents = db.query(Document).filter(Document.id.in_(document_ids)).all()
    found_ids = {d.id for d in documents}
    missing_ids = set(document_ids) - found_ids
    if missing_ids:
        raise ExportError(f"Document(s) not found: {sorted(missing_ids)}")

    for document in documents:
        try:
            _assert_approved(document)
        except ExportError as exc:
            log_event(
                db,
                event_type="export_failed",
                message=str(exc),
                document_id=document.id,
                details={"export_type": "csv"},
            )
            raise

    rows = [_document_export_row(d) for d in documents]

    # Union of all keys across rows, with the envelope fields first.
    envelope_keys = ["document_id", "filename", "document_type", "approval_status", "approved_at"]
    extra_keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in envelope_keys and key not in extra_keys:
                extra_keys.append(key)
    fieldnames = envelope_keys + extra_keys

    os.makedirs(settings.export_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    filename = f"export_{timestamp}.csv"
    export_path = os.path.join(settings.export_dir, filename)

    with open(export_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    return _record_export(db, documents, ExportType.CSV, export_path)


def export_documents_json(db: Session, document_ids: list[int]) -> ExportLog:
    """Export one or more approved documents to a single JSON file (a list of records)."""
    documents = db.query(Document).filter(Document.id.in_(document_ids)).all()
    found_ids = {d.id for d in documents}
    missing_ids = set(document_ids) - found_ids
    if missing_ids:
        raise ExportError(f"Document(s) not found: {sorted(missing_ids)}")

    for document in documents:
        try:
            _assert_approved(document)
        except ExportError as exc:
            log_event(
                db,
                event_type="export_failed",
                message=str(exc),
                document_id=document.id,
                details={"export_type": "json"},
            )
            raise

    records = []
    for document in documents:
        approval = document.approval
        records.append(
            {
                "document_id": document.id,
                "filename": document.filename,
                "document_type": document.document_type.value if document.document_type else None,
                "approval_status": approval.status.value if approval else None,
                "approved_at": approval.decided_at.isoformat() if approval and approval.decided_at else None,
                "fields": (approval.final_data if approval else None) or {},
            }
        )

    os.makedirs(settings.export_dir, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    filename = f"export_{timestamp}.json"
    export_path = os.path.join(settings.export_dir, filename)

    with open(export_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, default=str)

    return _record_export(db, documents, ExportType.JSON, export_path)


def _record_export(db: Session, documents: list[Document], export_type: ExportType, export_path: str) -> ExportLog:
    """Create one ExportLog row per exported document (all pointing at the
    same file), update each document's status to EXPORTED, and write audit
    log entries. Returns the last ExportLog created (the router can list
    all logs for the full set via GET /export-logs).
    """
    last_log: Optional[ExportLog] = None

    for document in documents:
        export_log = ExportLog(
            document_id=document.id,
            export_type=export_type,
            export_path=export_path,
            export_status=ExportStatus.SUCCESS,
        )
        db.add(export_log)

        document.status = DocumentStatus.EXPORTED

        db.commit()
        db.refresh(export_log)
        db.refresh(document)

        log_event(
            db,
            event_type="export_completed",
            message=f"Document exported as {export_type.value.upper()} to {export_path}.",
            document_id=document.id,
            details={"export_type": export_type.value, "export_path": export_path},
        )

        last_log = export_log

    return last_log
