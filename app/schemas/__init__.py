"""
Pydantic schemas used for API request/response bodies and for validating
AI extraction output.

Kept separate from SQLAlchemy models (app/models.py) so the database layer
and the API contract can evolve independently.
"""

from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import (
    DocumentType,
    DocumentStatus,
    ExtractionMethod,
    ExtractionStatus,
    ValidationStatus,
    ValidationLevel,
    ApprovalStatus,
    ExportType,
    ExportStatus,
)



# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class ValidationIssue(BaseModel):
    level: ValidationLevel
    rule: str
    field: Optional[str] = None
    message: str


class ValidationResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    status: ValidationStatus
    issues: Optional[list[ValidationIssue]] = None
    created_at: datetime

# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    file_type: str
    file_size_bytes: Optional[int] = None
    upload_time: datetime
    status: DocumentStatus
    document_type: Optional[DocumentType] = None
    classification_confidence: Optional[float] = None
    classification_reason: Optional[str] = None
    expected_document_type: Optional[DocumentType] = None
    notes: Optional[str] = None
    is_demo: bool
    validation_result: Optional[ValidationResultOut] = None


class UploadResponse(BaseModel):
    document: DocumentOut
    message: str


# ---------------------------------------------------------------------------
# Extracted text
# ---------------------------------------------------------------------------

class ExtractedTextOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    raw_text: str
    extraction_method: ExtractionMethod
    extraction_status: ExtractionStatus
    extraction_confidence: Optional[float] = None
    error_message: Optional[str] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Per-document-type extracted fields
#
# These describe the *shape* of `extracted_fields` for each document type.
# The AI/mock extractor returns a plain dict validated against one of these,
# and it's stored as JSON in ExtractedData.extracted_fields.
# ---------------------------------------------------------------------------

class LineItem(BaseModel):
    description: str = ""
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None


class InvoiceFields(BaseModel):
    vendor_name: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None     # ISO date YYYY-MM-DD
    due_date: Optional[str] = None         # ISO date YYYY-MM-DD
    currency: Optional[str] = None
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    total_amount: Optional[float] = None
    payment_terms: Optional[str] = None
    line_items: list[LineItem] = Field(default_factory=list)
    bank_details: Optional[str] = None


class ReceiptFields(BaseModel):
    merchant_name: Optional[str] = None
    receipt_number: Optional[str] = None
    transaction_date: Optional[str] = None  # ISO date YYYY-MM-DD
    payment_method: Optional[str] = None
    currency: Optional[str] = None
    tax: Optional[float] = None
    total_amount: Optional[float] = None
    items: list[LineItem] = Field(default_factory=list)


class PurchaseOrderFields(BaseModel):
    po_number: Optional[str] = None
    buyer_name: Optional[str] = None
    supplier_name: Optional[str] = None
    order_date: Optional[str] = None       # ISO date YYYY-MM-DD
    delivery_date: Optional[str] = None    # ISO date YYYY-MM-DD
    currency: Optional[str] = None
    total_amount: Optional[float] = None
    line_items: list[LineItem] = Field(default_factory=list)


class ContractFields(BaseModel):
    party_a: Optional[str] = None
    party_b: Optional[str] = None
    effective_date: Optional[str] = None   # ISO date YYYY-MM-DD
    end_date: Optional[str] = None         # ISO date YYYY-MM-DD
    payment_terms: Optional[str] = None
    key_obligations: Optional[str] = None
    termination_clause: Optional[str] = None
    risks: Optional[str] = None


# Maps DocumentType -> the Pydantic model describing its extracted_fields shape.
DOCUMENT_FIELD_SCHEMAS: dict[DocumentType, type[BaseModel]] = {
    DocumentType.INVOICE: InvoiceFields,
    DocumentType.RECEIPT: ReceiptFields,
    DocumentType.PURCHASE_ORDER: PurchaseOrderFields,
    DocumentType.CONTRACT: ContractFields,
}


# ---------------------------------------------------------------------------
# AI classification + extraction - structured output contracts
# ---------------------------------------------------------------------------

class ClassificationResult(BaseModel):
    """Output of the AI classification task."""

    document_type: DocumentType
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class ExtractionResult(BaseModel):
    """Output of the AI field-extraction task.

    `extracted_fields` is a plain dict whose shape should match
    DOCUMENT_FIELD_SCHEMAS[document_type] - validated separately by the
    extraction service, since the schema depends on document_type.
    """

    document_type: DocumentType
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    uncertain_fields: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str = ""


class ExtractedDataOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    document_type: DocumentType
    extracted_fields: Optional[Any] = None
    missing_fields: Optional[Any] = None
    uncertain_fields: Optional[Any] = None
    overall_confidence: float
    summary: str
    raw_ai_response: Optional[Any] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Approval / review
# ---------------------------------------------------------------------------

class ApprovalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    status: ApprovalStatus
    decided_at: Optional[datetime] = None
    reviewer_note: Optional[str] = None
    edited_fields: Optional[Any] = None
    final_data: Optional[Any] = None
    created_at: datetime
    updated_at: datetime


class FieldEditRequest(BaseModel):
    """Body for editing extracted fields before approval.

    `fields` should be the full corrected extracted_fields dict (same shape
    as ExtractedData.extracted_fields for this document's type).
    """
    fields: dict[str, Any]


class ReviewDecisionRequest(BaseModel):
    """Body for approve/reject/needs-correction decisions."""
    reviewer_note: Optional[str] = None


class ReviewDecisionResponse(BaseModel):
    document: DocumentOut
    approval: ApprovalOut
    message: str


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

class ExportLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    export_type: ExportType
    export_path: Optional[str] = None
    export_status: ExportStatus
    error_message: Optional[str] = None
    export_time: datetime


class ExportResponse(BaseModel):
    export_log: ExportLogOut
    message: str


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: Optional[int] = None
    event_type: str
    message: str
    details: Optional[Any] = None
    actor: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Document detail (combines everything)
# ---------------------------------------------------------------------------

class DocumentDetail(DocumentOut):
    extracted_text: Optional[ExtractedTextOut] = None
    extracted_data: Optional[ExtractedDataOut] = None
    validation_result: Optional[ValidationResultOut] = None
    approval: Optional[ApprovalOut] = None


# ---------------------------------------------------------------------------
# Dashboard metrics
# ---------------------------------------------------------------------------

class DashboardMetrics(BaseModel):
    total_documents: int
    processed_documents: int
    pending_review: int
    approved_documents: int
    rejected_documents: int
    exported_documents: int
    average_confidence: Optional[float] = None


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    app_name: str
    env: str
    demo_mode: bool
    database_connected: bool
