"""
Database models.

Traceability is the core requirement of this system:

    Uploaded -> Text Extracted -> Classified -> Extracted -> Validated
    -> Pending Review -> Approved/Rejected/Needs Correction -> Exported

Each table below maps onto one stage of that lifecycle, plus an
append-only audit log that records every event across all stages.
"""

import enum
from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Enum as SAEnum,
    JSON,
)
from sqlalchemy.orm import relationship

from app.database import Base


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DocumentType(str, enum.Enum):
    INVOICE = "invoice"
    RECEIPT = "receipt"
    PURCHASE_ORDER = "purchase_order"
    CONTRACT = "contract"
    UNKNOWN = "unknown"


class DocumentStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    TEXT_EXTRACTED = "text_extracted"
    EXTRACTION_FAILED = "extraction_failed"
    CLASSIFIED = "classified"
    EXTRACTED = "extracted"
    VALIDATED = "validated"
    PENDING_REVIEW = "pending_review"
    NEEDS_CORRECTION = "needs_correction"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPORTED = "exported"


class ExtractionMethod(str, enum.Enum):
    PDF_TEXT = "pdf_text"
    OCR = "ocr"
    MOCK = "mock"


class ExtractionStatus(str, enum.Enum):
    SUCCESS = "success"
    FAILED = "failed"


class ValidationStatus(str, enum.Enum):
    VALID = "valid"
    WARNING = "warning"
    FAILED = "failed"
    REQUIRES_REVIEW = "requires_review"


class ValidationLevel(str, enum.Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CORRECTION = "needs_correction"


class ExportType(str, enum.Enum):
    CSV = "csv"
    JSON = "json"


class ExportStatus(str, enum.Enum):
    SUCCESS = "success"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Document(Base):
    """An uploaded business document and its current lifecycle status."""

    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)

    filename = Column(String(255), nullable=False)
    file_type = Column(String(16), nullable=False)       # pdf | png | jpg | jpeg
    file_path = Column(String(512), nullable=False)
    file_size_bytes = Column(Integer, nullable=True)

    upload_time = Column(DateTime, default=datetime.utcnow)
    status = Column(SAEnum(DocumentStatus), nullable=False, default=DocumentStatus.UPLOADED)

    # Set by the classification stage.
    document_type = Column(SAEnum(DocumentType), nullable=True)
    classification_confidence = Column(Float, nullable=True)
    classification_reason = Column(Text, nullable=True)

    # Optional fields supplied at upload time.
    expected_document_type = Column(SAEnum(DocumentType), nullable=True)
    notes = Column(Text, nullable=True)

    is_demo = Column(Boolean, default=False)

    extracted_text = relationship(
        "ExtractedText", back_populates="document", uselist=False, cascade="all, delete-orphan"
    )
    extracted_data = relationship(
        "ExtractedData", back_populates="document", uselist=False, cascade="all, delete-orphan"
    )
    validation_result = relationship(
        "ValidationResult", back_populates="document", uselist=False, cascade="all, delete-orphan"
    )
    approval = relationship(
        "Approval", back_populates="document", uselist=False, cascade="all, delete-orphan"
    )
    export_logs = relationship("ExportLog", back_populates="document", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="document", cascade="all, delete-orphan")


class ExtractedText(Base):
    """Raw text extracted from a document via PDF parsing, OCR, or mock data."""

    __tablename__ = "extracted_text"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), unique=True, nullable=False)

    raw_text = Column(Text, default="")
    extraction_method = Column(SAEnum(ExtractionMethod), nullable=False, default=ExtractionMethod.MOCK)
    extraction_status = Column(SAEnum(ExtractionStatus), nullable=False, default=ExtractionStatus.SUCCESS)
    extraction_confidence = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("Document", back_populates="extracted_text")


class ExtractedData(Base):
    """Structured AI output: classification + per-document-type field extraction."""

    __tablename__ = "extracted_data"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), unique=True, nullable=False)

    document_type = Column(SAEnum(DocumentType), nullable=False, default=DocumentType.UNKNOWN)

    # Main structured fields, shape depends on document_type
    # (see app/schemas for the per-type field definitions).
    extracted_fields = Column(JSON, nullable=True)

    missing_fields = Column(JSON, nullable=True)     # list[str]
    uncertain_fields = Column(JSON, nullable=True)    # list[str]

    overall_confidence = Column(Float, nullable=False, default=0.0)
    summary = Column(Text, default="")

    # Full raw AI response, kept for debugging / transparency.
    raw_ai_response = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("Document", back_populates="extracted_data")


class ValidationResult(Base):
    """Result of running the rule-based validation engine on extracted_data."""

    __tablename__ = "validation_results"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), unique=True, nullable=False)

    status = Column(SAEnum(ValidationStatus), nullable=False, default=ValidationStatus.REQUIRES_REVIEW)

    # List of {"level": "error"|"warning"|"info", "rule": str, "field": str|None, "message": str}
    issues = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("Document", back_populates="validation_result")


class Approval(Base):
    """Human review decision for a document."""

    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), unique=True, nullable=False)

    status = Column(SAEnum(ApprovalStatus), nullable=False, default=ApprovalStatus.PENDING)
    decided_at = Column(DateTime, nullable=True)
    reviewer_note = Column(Text, nullable=True)

    # Fields the human changed, e.g. {"total_amount": {"old": 1080.0, "new": 1180.0}}
    edited_fields = Column(JSON, nullable=True)

    # The final, human-confirmed data - this is what gets exported.
    final_data = Column(JSON, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    document = relationship("Document", back_populates="approval")


class ExportLog(Base):
    """Record of an export of an approved document."""

    __tablename__ = "export_logs"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)

    export_type = Column(SAEnum(ExportType), nullable=False)
    export_path = Column(String(512), nullable=True)
    export_status = Column(SAEnum(ExportStatus), nullable=False, default=ExportStatus.SUCCESS)
    error_message = Column(Text, nullable=True)

    export_time = Column(DateTime, default=datetime.utcnow)

    document = relationship("Document", back_populates="export_logs")


class AuditLog(Base):
    """Append-only log of every meaningful system event.

    Answers: what happened, when, and why?
    """

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=True)

    event_type = Column(String(64), nullable=False)
    # e.g. "document_uploaded", "text_extracted", "extraction_failed",
    #      "document_classified", "fields_extracted", "validation_completed",
    #      "field_edited", "document_approved", "document_rejected",
    #      "export_completed", "export_failed"

    message = Column(Text, nullable=False, default="")
    details = Column(JSON, nullable=True)

    actor = Column(String(64), nullable=False, default="system")  # "system" | "user"

    created_at = Column(DateTime, default=datetime.utcnow)

    document = relationship("Document", back_populates="audit_logs")
