"""
Document endpoints:
  POST /documents/upload  - upload a new document (PDF/PNG/JPG/JPEG)
  GET  /documents         - list documents (filter by status/document_type)
  GET  /documents/{id}    - document detail, including extraction/analysis/
                             validation/approval if available
  GET  /documents/{id}/file - download/view the original uploaded file
"""

from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, DocumentStatus, DocumentType
from app.schemas import DocumentDetail, DocumentOut, UploadResponse
from app.services.upload import create_document, UploadValidationError

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    expected_document_type: Optional[DocumentType] = Form(None),
    notes: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Upload a new document.

    Accepted file types: pdf, png, jpg, jpeg (configurable via
    ALLOWED_FILE_TYPES). Files are validated for type, size, and emptiness
    before being stored. The resulting document starts at status='uploaded'
    and is ready for text extraction (Phase 3).
    """
    content = await file.read()

    try:
        document = create_document(
            db,
            filename=file.filename,
            content=content,
            expected_document_type=expected_document_type,
            notes=notes,
        )
    except UploadValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    return UploadResponse(document=document, message=f"Document '{file.filename}' uploaded successfully.")


@router.get("", response_model=list[DocumentOut])
def list_documents(
    status: Optional[DocumentStatus] = Query(None, description="Filter by lifecycle status"),
    document_type: Optional[DocumentType] = Query(None, description="Filter by classified document type"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List uploaded documents, most recently uploaded first."""
    query = db.query(Document)
    if status is not None:
        query = query.filter(Document.status == status)
    if document_type is not None:
        query = query.filter(Document.document_type == document_type)

    return query.order_by(Document.upload_time.desc()).offset(offset).limit(limit).all()


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: int, db: Session = Depends(get_db)):
    """Get full document detail: metadata, extracted text, AI analysis,
    validation results, and approval status (whichever stages have run)."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/{document_id}/file")
def get_document_file(document_id: int, db: Session = Depends(get_db)):
    """Download/view the original uploaded file."""
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    media_types = {
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
    }

    return FileResponse(
        path=document.file_path,
        media_type=media_types.get(document.file_type, "application/octet-stream"),
        filename=document.filename,
    )
