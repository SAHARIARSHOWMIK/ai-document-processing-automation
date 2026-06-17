"""
Dashboard support endpoints:
  GET  /dashboard/metrics - summary counts for the dashboard home page
  GET  /audit-logs        - full audit trail, most recent first
  POST /demo/seed         - load sample documents (invoice/receipt/PO/contract scenarios)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuditLog, Document, DocumentStatus, ExtractedData
from app.schemas import AuditLogOut, DashboardMetrics, DocumentOut
from app.services.demo_seed import seed_demo_documents

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/metrics", response_model=DashboardMetrics)
def get_metrics(db: Session = Depends(get_db)):
    """Summary counts used by the dashboard home page."""
    total_documents = db.query(Document).count()

    processed_documents = (
        db.query(Document)
        .filter(
            Document.status.in_(
                [
                    DocumentStatus.EXTRACTED,
                    DocumentStatus.VALIDATED,
                    DocumentStatus.PENDING_REVIEW,
                    DocumentStatus.NEEDS_CORRECTION,
                    DocumentStatus.APPROVED,
                    DocumentStatus.REJECTED,
                    DocumentStatus.EXPORTED,
                ]
            )
        )
        .count()
    )

    pending_review = (
        db.query(Document)
        .filter(Document.status.in_([DocumentStatus.PENDING_REVIEW, DocumentStatus.NEEDS_CORRECTION]))
        .count()
    )
    approved_documents = db.query(Document).filter(
        Document.status.in_([DocumentStatus.APPROVED, DocumentStatus.EXPORTED])
    ).count()
    rejected_documents = db.query(Document).filter(Document.status == DocumentStatus.REJECTED).count()
    exported_documents = db.query(Document).filter(Document.status == DocumentStatus.EXPORTED).count()

    avg_confidence = db.query(func.avg(ExtractedData.overall_confidence)).scalar()

    return DashboardMetrics(
        total_documents=total_documents,
        processed_documents=processed_documents,
        pending_review=pending_review,
        approved_documents=approved_documents,
        rejected_documents=rejected_documents,
        exported_documents=exported_documents,
        average_confidence=round(avg_confidence, 2) if avg_confidence is not None else None,
    )


@router.get("/audit-logs", response_model=list[AuditLogOut])
def list_audit_logs(
    document_id: int | None = Query(None, description="Filter by document ID"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Full audit trail, most recent first."""
    query = db.query(AuditLog)
    if document_id is not None:
        query = query.filter(AuditLog.document_id == document_id)
    return query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()


@router.post("/demo/seed", response_model=list[DocumentOut])
def seed_demo(db: Session = Depends(get_db)):
    """Load the 6 sample documents (clean invoice, invoice with wrong total,
    invoice missing due date, receipt, purchase order, contract) so the
    full pipeline can be tested without uploading real files.

    Safe to call multiple times - scenarios already seeded (matched by
    filename) are skipped, so this never creates duplicates.
    """
    return seed_demo_documents(db)
