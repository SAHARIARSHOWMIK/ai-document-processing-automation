"""
Upload service.

Handles validation and storage of uploaded files, and creates the initial
Document record (status=UPLOADED).

Validation checks performed (per the project spec):
  - File type    : must be in settings.allowed_file_types_list (pdf/png/jpg/jpeg)
  - File size    : must not exceed settings.max_upload_size_bytes
  - Empty file   : rejected
  - Duplicate filename: allowed, but flagged with an audit warning so it's
    visible in the trail (the stored file itself always gets a unique name,
    so duplicates never overwrite each other)

If any check fails, UploadValidationError is raised before any file is
written or any Document row is created - the router turns this into an
HTTP 400/413/415 response. Because no Document exists yet in that case,
there is no "Upload Failed" *row* - the failure is surfaced directly to the
caller. This is a deliberate simplification noted in the README.
"""

import os
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Document, DocumentStatus, DocumentType
from app.services.audit import log_event


class UploadValidationError(Exception):
    """Raised when an uploaded file fails validation. Carries an HTTP status code."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _get_extension(filename: str) -> str:
    _, ext = os.path.splitext(filename or "")
    return ext.lstrip(".").lower()


def validate_upload(filename: str, content: bytes) -> str:
    """Validate an uploaded file's name and content.

    Returns the validated (lowercased) file extension.
    Raises UploadValidationError on any failed check.
    """
    if not filename:
        raise UploadValidationError("No filename provided.", status_code=400)

    extension = _get_extension(filename)
    if extension not in settings.allowed_file_types_list:
        allowed = ", ".join(settings.allowed_file_types_list)
        raise UploadValidationError(
            f"Unsupported file type '.{extension}'. Allowed types: {allowed}.",
            status_code=415,
        )

    if len(content) == 0:
        raise UploadValidationError("Uploaded file is empty.", status_code=400)

    if len(content) > settings.max_upload_size_bytes:
        raise UploadValidationError(
            f"File exceeds the maximum allowed size of {settings.max_upload_size_mb} MB.",
            status_code=413,
        )

    return extension


def save_file(filename: str, content: bytes, extension: str) -> str:
    """Write the file's bytes to settings.upload_dir under a unique name.

    Returns the path the file was saved to.
    """
    os.makedirs(settings.upload_dir, exist_ok=True)

    unique_name = f"{uuid.uuid4().hex}.{extension}"
    file_path = os.path.join(settings.upload_dir, unique_name)

    with open(file_path, "wb") as f:
        f.write(content)

    return file_path


def create_document(
    db: Session,
    filename: str,
    content: bytes,
    expected_document_type: Optional[DocumentType] = None,
    notes: Optional[str] = None,
    is_demo: bool = False,
) -> Document:
    """Validate, store, and record a new uploaded document.

    Returns the created Document (status=UPLOADED).
    Raises UploadValidationError if validation fails (no side effects in that case).
    """
    extension = validate_upload(filename, content)

    # Duplicate filename check: informational only, doesn't block the upload.
    duplicate = db.query(Document).filter(Document.filename == filename).first()

    file_path = save_file(filename, content, extension)

    document = Document(
        filename=filename,
        file_type=extension,
        file_path=file_path,
        file_size_bytes=len(content),
        status=DocumentStatus.UPLOADED,
        expected_document_type=expected_document_type,
        notes=notes,
        is_demo=is_demo,
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    log_event(
        db,
        event_type="document_uploaded",
        message=f"Document '{filename}' uploaded ({len(content)} bytes).",
        document_id=document.id,
        details={"file_type": extension, "size_bytes": len(content)},
    )

    if duplicate:
        log_event(
            db,
            event_type="duplicate_filename_detected",
            message=(
                f"A document with filename '{filename}' was already uploaded "
                f"previously (document #{duplicate.id}). Both are kept as "
                f"separate records."
            ),
            document_id=document.id,
            details={"previous_document_id": duplicate.id},
        )

    return document
