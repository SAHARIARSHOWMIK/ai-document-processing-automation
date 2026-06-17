"""
Export endpoints:
  POST /export/csv             - export one or more approved documents to CSV
  POST /export/json            - export one or more approved documents to JSON
  GET  /export-logs            - list export history
  GET  /export/download/{path} - download a previously generated export file
"""

import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ExportLog
from app.schemas import ExportLogOut, ExportResponse
from app.services.export import ExportError, export_documents_csv, export_documents_json

router = APIRouter(tags=["export"])


class ExportRequest(BaseModel):
    document_ids: list[int]


@router.post("/export/csv", response_model=ExportResponse)
def export_csv(body: ExportRequest, db: Session = Depends(get_db)):
    """Export one or more documents to a single CSV file.

    Only approved documents can be exported - if any requested document
    is not approved, the whole request is rejected (400) and no file is
    written. Approve documents first via POST /documents/{id}/approve.
    """
    try:
        export_log = export_documents_csv(db, body.document_ids)
    except ExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return ExportResponse(export_log=export_log, message=f"Exported {len(body.document_ids)} document(s) to CSV.")


@router.post("/export/json", response_model=ExportResponse)
def export_json(body: ExportRequest, db: Session = Depends(get_db)):
    """Export one or more documents to a single JSON file.

    Only approved documents can be exported - if any requested document
    is not approved, the whole request is rejected (400) and no file is
    written. Approve documents first via POST /documents/{id}/approve.
    """
    try:
        export_log = export_documents_json(db, body.document_ids)
    except ExportError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return ExportResponse(export_log=export_log, message=f"Exported {len(body.document_ids)} document(s) to JSON.")


@router.get("/export-logs", response_model=list[ExportLogOut])
def list_export_logs(
    document_id: int | None = Query(None, description="Filter by document ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List export history, most recent first."""
    query = db.query(ExportLog)
    if document_id is not None:
        query = query.filter(ExportLog.document_id == document_id)
    return query.order_by(ExportLog.export_time.desc()).offset(offset).limit(limit).all()


@router.get("/export/download/{export_log_id}")
def download_export(export_log_id: int, db: Session = Depends(get_db)):
    """Download the export file associated with a given export log entry."""
    export_log = db.query(ExportLog).filter(ExportLog.id == export_log_id).first()
    if not export_log or not export_log.export_path:
        raise HTTPException(status_code=404, detail="Export log not found")

    if not os.path.exists(export_log.export_path):
        raise HTTPException(status_code=404, detail="Export file no longer exists on disk")

    media_type = "text/csv" if export_log.export_type.value == "csv" else "application/json"
    filename = os.path.basename(export_log.export_path)

    return FileResponse(path=export_log.export_path, media_type=media_type, filename=filename)
