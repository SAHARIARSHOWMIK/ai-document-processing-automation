"""
Validation engine.

Deliberately separate from the AI: "AI extracts. Validation checks."

Runs business-rule validation on ExtractedData.extracted_fields for a
document, per the rules in the project spec, and produces a
ValidationResult with an overall status and a list of issues
(errors/warnings/info).

Status determination:
  - any ERROR issue                          -> FAILED
  - overall AI confidence below the review
    threshold (even with no other issues)    -> REQUIRES_REVIEW
  - any WARNING issue (and no errors)        -> WARNING
  - otherwise                                -> VALID

Approval rules (enforced in the review service, Phase 6):
  - FAILED documents cannot be approved until corrected.
  - WARNING / REQUIRES_REVIEW documents can be approved after human review.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Document,
    DocumentStatus,
    DocumentType,
    ExtractedData,
    ValidationLevel,
    ValidationResult,
    ValidationStatus,
)
from app.schemas import ValidationIssue
from app.services.audit import log_event

AMOUNT_TOLERANCE = 0.01


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except (ValueError, TypeError):
        return None


def _issue(level: ValidationLevel, rule: str, message: str, field: Optional[str] = None) -> ValidationIssue:
    return ValidationIssue(level=level, rule=rule, field=field, message=message)


def _require(fields: dict, field: str, label: str, rule: str) -> Optional[ValidationIssue]:
    if not fields.get(field):
        return _issue(ValidationLevel.ERROR, rule, f"{label} is missing.", field=field)
    return None


def _check_currency(fields: dict, rule: str = "currency_validation") -> Optional[ValidationIssue]:
    currency = fields.get("currency")
    if not currency:
        return _issue(ValidationLevel.INFO, rule, "Currency was not specified.", field="currency")
    if currency.upper() not in settings.valid_currencies_list:
        allowed = ", ".join(settings.valid_currencies_list)
        return _issue(
            ValidationLevel.WARNING,
            rule,
            f"Currency '{currency}' is not one of the recognized currencies ({allowed}).",
            field="currency",
        )
    return None


# ---------------------------------------------------------------------------
# Invoice validation
# ---------------------------------------------------------------------------

def validate_invoice(db: Session, document: Document, fields: dict) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for field, label in [
        ("vendor_name", "Vendor name"),
        ("invoice_number", "Invoice number"),
        ("invoice_date", "Invoice date"),
        ("total_amount", "Total amount"),
    ]:
        issue = _require(fields, field, label, "required_field_validation")
        if issue:
            issues.append(issue)

    # Due date should be after invoice date
    invoice_date = _parse_date(fields.get("invoice_date"))
    due_date = _parse_date(fields.get("due_date"))
    if due_date and invoice_date and due_date < invoice_date:
        issues.append(
            _issue(
                ValidationLevel.ERROR,
                "date_validation",
                f"Due date ({fields['due_date']}) is before the invoice date ({fields['invoice_date']}).",
                field="due_date",
            )
        )
    elif not fields.get("due_date"):
        issues.append(_issue(ValidationLevel.WARNING, "required_field_validation", "Due date is missing.", field="due_date"))

    # Total should match subtotal + tax
    subtotal = fields.get("subtotal")
    tax = fields.get("tax")
    total = fields.get("total_amount")
    if subtotal is not None and tax is not None and total is not None:
        expected = round(subtotal + tax, 2)
        if abs(expected - total) > AMOUNT_TOLERANCE:
            issues.append(
                _issue(
                    ValidationLevel.WARNING,
                    "amount_validation",
                    f"Total ({total}) does not match subtotal + tax ({subtotal} + {tax} = {expected}).",
                    field="total_amount",
                )
            )

    # Currency validation
    currency_issue = _check_currency(fields)
    if currency_issue:
        issues.append(currency_issue)

    # High amount warning
    if total is not None and total > settings.high_amount_warning_threshold:
        issues.append(
            _issue(
                ValidationLevel.WARNING,
                "amount_validation",
                f"Total amount ({total}) exceeds the high-amount review threshold "
                f"({settings.high_amount_warning_threshold}).",
                field="total_amount",
            )
        )

    # Duplicate invoice: same vendor + invoice number on another document
    vendor_name = fields.get("vendor_name")
    invoice_number = fields.get("invoice_number")
    if vendor_name and invoice_number:
        others = (
            db.query(ExtractedData)
            .filter(
                ExtractedData.document_type == DocumentType.INVOICE,
                ExtractedData.document_id != document.id,
            )
            .all()
        )
        for other in others:
            other_fields = other.extracted_fields or {}
            if other_fields.get("vendor_name") == vendor_name and other_fields.get("invoice_number") == invoice_number:
                issues.append(
                    _issue(
                        ValidationLevel.WARNING,
                        "duplicate_validation",
                        f"Possible duplicate invoice: vendor '{vendor_name}' and invoice number "
                        f"'{invoice_number}' also appear on document #{other.document_id}.",
                        field="invoice_number",
                    )
                )
                break

    return issues


# ---------------------------------------------------------------------------
# Receipt validation
# ---------------------------------------------------------------------------

def validate_receipt(db: Session, document: Document, fields: dict) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for field, label in [
        ("merchant_name", "Merchant name"),
        ("transaction_date", "Transaction date"),
        ("total_amount", "Total amount"),
    ]:
        issue = _require(fields, field, label, "required_field_validation")
        if issue:
            issues.append(issue)

    total = fields.get("total_amount")
    if total is not None and total <= 0:
        issues.append(
            _issue(
                ValidationLevel.ERROR,
                "amount_validation",
                f"Total amount ({total}) must be positive.",
                field="total_amount",
            )
        )

    currency_issue = _check_currency(fields)
    if currency_issue:
        issues.append(currency_issue)

    return issues


# ---------------------------------------------------------------------------
# Purchase order validation
# ---------------------------------------------------------------------------

def validate_purchase_order(db: Session, document: Document, fields: dict) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for field, label in [
        ("po_number", "PO number"),
        ("buyer_name", "Buyer name"),
        ("supplier_name", "Supplier name"),
        ("total_amount", "Total amount"),
    ]:
        issue = _require(fields, field, label, "required_field_validation")
        if issue:
            issues.append(issue)

    # Delivery date should be after order date
    order_date = _parse_date(fields.get("order_date"))
    delivery_date = _parse_date(fields.get("delivery_date"))
    if order_date and delivery_date and delivery_date < order_date:
        issues.append(
            _issue(
                ValidationLevel.ERROR,
                "date_validation",
                f"Delivery date ({fields['delivery_date']}) is before the order date ({fields['order_date']}).",
                field="delivery_date",
            )
        )

    # Total should match sum of line items
    line_items = fields.get("line_items") or []
    total = fields.get("total_amount")
    if line_items and total is not None:
        items_sum = round(sum((item.get("amount") or 0) for item in line_items), 2)
        if abs(items_sum - total) > AMOUNT_TOLERANCE:
            issues.append(
                _issue(
                    ValidationLevel.WARNING,
                    "amount_validation",
                    f"Total ({total}) does not match the sum of line items ({items_sum}).",
                    field="total_amount",
                )
            )

    # Duplicate PO number on another document
    po_number = fields.get("po_number")
    if po_number:
        others = (
            db.query(ExtractedData)
            .filter(
                ExtractedData.document_type == DocumentType.PURCHASE_ORDER,
                ExtractedData.document_id != document.id,
            )
            .all()
        )
        for other in others:
            other_fields = other.extracted_fields or {}
            if other_fields.get("po_number") == po_number:
                issues.append(
                    _issue(
                        ValidationLevel.WARNING,
                        "duplicate_validation",
                        f"Possible duplicate PO: number '{po_number}' also appears on document #{other.document_id}.",
                        field="po_number",
                    )
                )
                break

    return issues


# ---------------------------------------------------------------------------
# Contract validation
# ---------------------------------------------------------------------------

def validate_contract(db: Session, document: Document, fields: dict) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if not fields.get("party_a") or not fields.get("party_b"):
        issues.append(
            _issue(
                ValidationLevel.ERROR,
                "required_field_validation",
                "At least two contracting parties (party_a and party_b) should be identified.",
                field="parties",
            )
        )

    if not fields.get("effective_date"):
        issues.append(
            _issue(
                ValidationLevel.ERROR,
                "required_field_validation",
                "Effective date (contract start date) is missing.",
                field="effective_date",
            )
        )

    if not fields.get("end_date"):
        issues.append(
            _issue(
                ValidationLevel.INFO,
                "date_validation",
                "End date was not identified - this may be an open-ended contract.",
                field="end_date",
            )
        )

    if not fields.get("payment_terms"):
        issues.append(
            _issue(
                ValidationLevel.WARNING,
                "risk_validation",
                "Payment terms could not be identified - this is a business risk.",
                field="payment_terms",
            )
        )

    if not fields.get("termination_clause"):
        issues.append(
            _issue(
                ValidationLevel.WARNING,
                "risk_validation",
                "Termination clause could not be identified - this is a contract risk.",
                field="termination_clause",
            )
        )

    if not fields.get("risks"):
        issues.append(
            _issue(
                ValidationLevel.INFO,
                "risk_validation",
                "No liability/penalty terms were extracted for risk review.",
                field="risks",
            )
        )

    return issues


# ---------------------------------------------------------------------------
# Dispatcher / status determination
# ---------------------------------------------------------------------------

_VALIDATORS = {
    DocumentType.INVOICE: validate_invoice,
    DocumentType.RECEIPT: validate_receipt,
    DocumentType.PURCHASE_ORDER: validate_purchase_order,
    DocumentType.CONTRACT: validate_contract,
}


def _determine_status(issues: list[ValidationIssue], overall_confidence: float) -> ValidationStatus:
    if any(i.level == ValidationLevel.ERROR for i in issues):
        return ValidationStatus.FAILED
    if overall_confidence < settings.classification_review_threshold:
        return ValidationStatus.REQUIRES_REVIEW
    if any(i.level == ValidationLevel.WARNING for i in issues):
        return ValidationStatus.WARNING
    return ValidationStatus.VALID


def run_validation(db: Session, document: Document) -> ValidationResult:
    """Run the validation engine for a document and persist the result.

    Requires document.extracted_data to exist (i.e. field extraction has
    run). After validation, document.status becomes 'pending_review' -
    every validated document, regardless of validation outcome, moves to
    the human review queue (the validation *status* itself, stored on
    ValidationResult, communicates whether there are errors/warnings).
    """
    extracted_data: Optional[ExtractedData] = document.extracted_data
    if not extracted_data:
        raise ValueError(f"Document {document.id} has no extracted data. Run field extraction first.")

    fields = extracted_data.extracted_fields or {}
    validator = _VALIDATORS.get(extracted_data.document_type)

    issues: list[ValidationIssue] = []
    if validator:
        issues = validator(db, document, fields)

    # Confidence validation: flag (but don't duplicate REQUIRES_REVIEW logic -
    # _determine_status already checks confidence directly).
    if extracted_data.overall_confidence < settings.classification_review_threshold:
        issues.append(
            _issue(
                ValidationLevel.WARNING,
                "confidence_validation",
                f"AI extraction confidence ({extracted_data.overall_confidence:.2f}) is below the "
                f"review threshold ({settings.classification_review_threshold:.2f}).",
            )
        )

    for missing_field in extracted_data.missing_fields or []:
        issues.append(
            _issue(
                ValidationLevel.INFO,
                "missing_field_reported_by_ai",
                f"AI reported missing field: {missing_field}",
                field=missing_field,
            )
        )

    for uncertain_field in extracted_data.uncertain_fields or []:
        issues.append(
            _issue(
                ValidationLevel.INFO,
                "uncertain_field_reported_by_ai",
                f"AI reported uncertain field: {uncertain_field}",
                field=uncertain_field,
            )
        )

    status = _determine_status(issues, extracted_data.overall_confidence)

    existing = db.query(ValidationResult).filter(ValidationResult.document_id == document.id).first()
    if existing:
        record = existing
    else:
        record = ValidationResult(document_id=document.id)
        db.add(record)

    record.status = status
    record.issues = [issue.model_dump() for issue in issues]

    document.status = DocumentStatus.PENDING_REVIEW

    db.commit()
    db.refresh(record)
    db.refresh(document)

    error_count = sum(1 for i in issues if i.level == ValidationLevel.ERROR)
    warning_count = sum(1 for i in issues if i.level == ValidationLevel.WARNING)

    log_event(
        db,
        event_type="validation_completed",
        message=(
            f"Validation completed: status={status.value} "
            f"({error_count} error(s), {warning_count} warning(s))."
        ),
        document_id=document.id,
        details={"status": status.value, "issue_count": len(issues)},
    )

    for issue in issues:
        if issue.level == ValidationLevel.ERROR:
            log_event(
                db,
                event_type="validation_error",
                message=issue.message,
                document_id=document.id,
                details={"rule": issue.rule, "field": issue.field},
            )
        elif issue.level == ValidationLevel.WARNING:
            log_event(
                db,
                event_type="validation_warning",
                message=issue.message,
                document_id=document.id,
                details={"rule": issue.rule, "field": issue.field},
            )

    return record
