"""
Mock document AI: classification + field extraction.

Used when DEMO_MODE=true (or no ANTHROPIC_API_KEY is set), so the full
pipeline - classify -> extract -> validate -> review -> export - works
without any AI credentials. Implemented with regex/keyword matching against
the sample document texts in demo_documents.py (and reasonably similar
real documents).

This is NOT a replacement for the real AI in ai_document.py - it exists
only to produce plausible, schema-valid structured output for demos and tests.
"""

import re

from app.models import DocumentType
from app.schemas import ClassificationResult, ExtractionResult


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _parse_amount(raw: str) -> float:
    return float(raw.replace(",", ""))


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _search(pattern: str, text: str, flags=0) -> str | None:
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else None


def _extract_section(text: str, header_pattern: str) -> str | None:
    """Find a numbered section like '4. Termination' and return the text
    up to (but not including) the next numbered section header, or end of text.
    """
    match = re.search(header_pattern + r"\s*\n", text, re.IGNORECASE)
    if not match:
        return None

    start = match.end()
    next_section = re.search(r"\n\d+\.\s+[A-Z]", text[start:])
    end = start + next_section.start() if next_section else len(text)

    section_text = text[start:end].strip()
    return re.sub(r"\s+", " ", section_text) or None


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def mock_classify(text: str) -> ClassificationResult:
    """Classify a document's extracted text by keyword matching."""
    upper = text.upper()

    if "PURCHASE ORDER" in upper or re.search(r"PO\s*Number", text, re.IGNORECASE):
        return ClassificationResult(
            document_type=DocumentType.PURCHASE_ORDER,
            confidence=0.94,
            reason="Contains 'Purchase Order' header and a PO number.",
        )

    if "SERVICE AGREEMENT" in upper or ("PARTY A" in upper and "PARTY B" in upper):
        return ClassificationResult(
            document_type=DocumentType.CONTRACT,
            confidence=0.93,
            reason="Contains agreement language and identifies two contracting parties.",
        )

    if "INVOICE" in upper and re.search(r"Invoice\s*Number", text, re.IGNORECASE):
        return ClassificationResult(
            document_type=DocumentType.INVOICE,
            confidence=0.95,
            reason="Contains an 'Invoice' header, invoice number, and total amount.",
        )

    if re.search(r"Receipt\s*Number", text, re.IGNORECASE) or "RECEIPT" in upper:
        return ClassificationResult(
            document_type=DocumentType.RECEIPT,
            confidence=0.90,
            reason="Contains a receipt number and a single transaction total.",
        )

    return ClassificationResult(
        document_type=DocumentType.UNKNOWN,
        confidence=0.30,
        reason="Could not find any document-type indicators (invoice/receipt/PO/contract keywords).",
    )


# ---------------------------------------------------------------------------
# Field extraction - Invoice
# ---------------------------------------------------------------------------

_TABLE_ROW_RE = re.compile(
    r"^(.+?)\s{2,}(\d+(?:\.\d+)?)\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s*$", re.MULTILINE
)


def _extract_line_items(text: str) -> list[dict]:
    items = []
    for match in _TABLE_ROW_RE.finditer(text):
        description, qty, unit_price, amount = match.groups()
        items.append(
            {
                "description": description.strip(),
                "quantity": float(qty),
                "unit_price": _parse_amount(unit_price),
                "amount": _parse_amount(amount),
            }
        )
    return items


def _extract_invoice_fields(text: str) -> ExtractionResult:
    fields: dict = {
        "vendor_name": _first_line(text) or None,
        "invoice_number": _search(r"Invoice Number:\s*(\S+)", text),
        "invoice_date": _search(r"Invoice Date:\s*(\d{4}-\d{2}-\d{2})", text),
        "due_date": _search(r"Due Date:\s*(\d{4}-\d{2}-\d{2})", text),
        "currency": _search(r"Currency:\s*(\w+)", text),
        "payment_terms": _search(r"Payment Terms:\s*(.+)", text),
        "bank_details": _search(r"Bank Details:\s*(.+)", text),
        "line_items": _extract_line_items(text),
    }

    subtotal = _search(r"Subtotal:\s*([\d,]+\.\d{2})", text)
    tax = _search(r"Tax(?:\s*\([^)]*\))?:\s*([\d,]+\.\d{2})", text)
    total = _search(r"Total Amount:\s*([\d,]+\.\d{2})", text)

    fields["subtotal"] = _parse_amount(subtotal) if subtotal else None
    fields["tax"] = _parse_amount(tax) if tax else None
    fields["total_amount"] = _parse_amount(total) if total else None

    required = ["vendor_name", "invoice_number", "invoice_date", "total_amount"]
    missing = [f for f in required if not fields.get(f)]

    confidence = 0.95 if not missing else 0.7
    summary = (
        f"Invoice {fields.get('invoice_number') or '(unknown number)'} from "
        f"{fields.get('vendor_name') or 'an unknown vendor'} for "
        f"{fields.get('total_amount')} {fields.get('currency') or ''}".strip()
        + (f", due {fields['due_date']}." if fields.get("due_date") else ", due date not specified.")
    )

    return ExtractionResult(
        document_type=DocumentType.INVOICE,
        extracted_fields=fields,
        missing_fields=missing,
        uncertain_fields=[],
        confidence=confidence,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Field extraction - Receipt
# ---------------------------------------------------------------------------

_RECEIPT_ITEM_RE = re.compile(r"^(.+?)\s{2,}([\d,]+\.\d{2})\s*$", re.MULTILINE)


def _extract_receipt_items(text: str) -> list[dict]:
    items = []
    # Only consider lines between "Item" header and "Tax:" to avoid matching
    # the Tax/Total lines themselves.
    header_match = re.search(r"^Item\s.*\n", text, re.MULTILINE)
    tax_match = re.search(r"^Tax:", text, re.MULTILINE)
    if not header_match:
        return items

    end = tax_match.start() if tax_match else len(text)
    section = text[header_match.end():end]

    for match in _RECEIPT_ITEM_RE.finditer(section):
        description, amount = match.groups()
        items.append({"description": description.strip(), "amount": _parse_amount(amount)})
    return items


def _extract_receipt_fields(text: str) -> ExtractionResult:
    fields: dict = {
        "merchant_name": _first_line(text) or None,
        "receipt_number": _search(r"Receipt Number:\s*(\S+)", text),
        "transaction_date": _search(r"Transaction Date:\s*(\d{4}-\d{2}-\d{2})", text),
        "payment_method": _search(r"Payment Method:\s*(.+)", text),
        "currency": _search(r"Currency:\s*(\w+)", text),
        "items": _extract_receipt_items(text),
    }

    tax = _search(r"Tax:\s*([\d,]+\.\d{2})", text)
    total = _search(r"Total Amount:\s*([\d,]+\.\d{2})", text)
    fields["tax"] = _parse_amount(tax) if tax else None
    fields["total_amount"] = _parse_amount(total) if total else None

    required = ["merchant_name", "transaction_date", "total_amount"]
    missing = [f for f in required if not fields.get(f)]

    confidence = 0.95 if not missing else 0.7
    summary = (
        f"Receipt {fields.get('receipt_number') or '(unknown number)'} from "
        f"{fields.get('merchant_name') or 'an unknown merchant'} for "
        f"{fields.get('total_amount')} {fields.get('currency') or ''}".strip()
    )

    return ExtractionResult(
        document_type=DocumentType.RECEIPT,
        extracted_fields=fields,
        missing_fields=missing,
        uncertain_fields=[],
        confidence=confidence,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Field extraction - Purchase Order
# ---------------------------------------------------------------------------

def _extract_po_fields(text: str) -> ExtractionResult:
    fields: dict = {
        "po_number": _search(r"PO Number:\s*(\S+)", text),
        "buyer_name": _search(r"Buyer:\s*(.+)", text),
        "supplier_name": _search(r"Supplier:\s*(.+)", text),
        "order_date": _search(r"Order Date:\s*(\d{4}-\d{2}-\d{2})", text),
        "delivery_date": _search(r"Delivery Date:\s*(\d{4}-\d{2}-\d{2})", text),
        "currency": _search(r"Currency:\s*(\w+)", text),
        "line_items": _extract_line_items(text),
    }

    total = _search(r"Total Amount:\s*([\d,]+\.\d{2})", text)
    fields["total_amount"] = _parse_amount(total) if total else None

    required = ["po_number", "buyer_name", "supplier_name", "total_amount"]
    missing = [f for f in required if not fields.get(f)]

    confidence = 0.94 if not missing else 0.7
    summary = (
        f"Purchase order {fields.get('po_number') or '(unknown number)'}: "
        f"{fields.get('buyer_name') or 'unknown buyer'} ordering from "
        f"{fields.get('supplier_name') or 'unknown supplier'}, total "
        f"{fields.get('total_amount')} {fields.get('currency') or ''}".strip()
    )

    return ExtractionResult(
        document_type=DocumentType.PURCHASE_ORDER,
        extracted_fields=fields,
        missing_fields=missing,
        uncertain_fields=[],
        confidence=confidence,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Field extraction - Contract
# ---------------------------------------------------------------------------

def _clean_party_name(raw: str | None) -> str | None:
    if not raw:
        return None
    # "Company A Sdn Bhd (\"Service Provider\")" -> "Company A Sdn Bhd"
    return re.sub(r"\s*\(.*\)\s*$", "", raw).strip() or None


def _extract_contract_fields(text: str) -> ExtractionResult:
    fields: dict = {
        "party_a": _clean_party_name(_search(r"Party A:\s*(.+)", text)),
        "party_b": _clean_party_name(_search(r"Party B:\s*(.+)", text)),
        "effective_date": _search(r"Effective Date:\s*(\d{4}-\d{2}-\d{2})", text),
        "end_date": _search(r"End Date:\s*(\d{4}-\d{2}-\d{2})", text),
        "payment_terms": _extract_section(text, r"\d+\.\s*Payment Terms"),
        "key_obligations": _extract_section(text, r"\d+\.\s*Obligations"),
        "termination_clause": _extract_section(text, r"\d+\.\s*Termination"),
        "risks": _extract_section(text, r"\d+\.\s*Liability"),
    }

    missing = []
    if not fields.get("party_a") or not fields.get("party_b"):
        missing.append("parties")
    if not fields.get("effective_date"):
        missing.append("effective_date")
    if not fields.get("payment_terms"):
        missing.append("payment_terms")
    if not fields.get("termination_clause"):
        missing.append("termination_clause")

    confidence = 0.93 if not missing else 0.7
    summary = (
        f"Service agreement between {fields.get('party_a') or 'Party A'} and "
        f"{fields.get('party_b') or 'Party B'}, effective {fields.get('effective_date') or 'an unspecified date'}"
        + (f" through {fields['end_date']}." if fields.get("end_date") else ".")
    )

    return ExtractionResult(
        document_type=DocumentType.CONTRACT,
        extracted_fields=fields,
        missing_fields=missing,
        uncertain_fields=[],
        confidence=confidence,
        summary=summary,
    )


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_EXTRACTORS = {
    DocumentType.INVOICE: _extract_invoice_fields,
    DocumentType.RECEIPT: _extract_receipt_fields,
    DocumentType.PURCHASE_ORDER: _extract_po_fields,
    DocumentType.CONTRACT: _extract_contract_fields,
}


def mock_extract_fields(document_type: DocumentType, text: str) -> ExtractionResult:
    """Extract structured fields for the given document type from text.

    For DocumentType.UNKNOWN (or any type without an extractor), returns an
    empty, low-confidence result rather than raising - callers should avoid
    calling this for UNKNOWN documents in the first place.
    """
    extractor = _EXTRACTORS.get(document_type)
    if not extractor:
        return ExtractionResult(
            document_type=document_type,
            extracted_fields={},
            missing_fields=[],
            uncertain_fields=[],
            confidence=0.0,
            summary="Document type is unknown; no field extraction template available.",
        )
    return extractor(text)
