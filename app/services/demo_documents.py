"""
Sample document texts.

These represent the *extracted text* of business documents (i.e. what
pdfplumber/OCR would return), used by:

  - the mock extraction path (DEMO_MODE=true or document.is_demo=true), so
    the full pipeline can be exercised without Tesseract/poppler installed
  - Phase 8 demo seeding, which creates Document rows pre-tagged with one
    of these scenario keys

Each scenario maps to one of the cases called out in the project spec's
"Demo Mode" page:
  - invoice_clean            : normal success flow
  - invoice_wrong_total       : validation warning (total mismatch)
  - invoice_missing_due_date  : validation warning (missing field)
  - receipt                   : receipt extraction
  - purchase_order            : PO workflow
  - contract                  : contract summary/risk extraction
"""

INVOICE_CLEAN = """\
ABC Sdn Bhd
123 Business Avenue, Kuala Lumpur, Malaysia

INVOICE

Invoice Number: INV-2026-001
Invoice Date: 2026-06-10
Due Date: 2026-06-30
Payment Terms: Net 30
Currency: MYR

Bill To: XYZ Company

Description                Qty   Unit Price   Amount
Web development services    1     1000.00     1000.00

Subtotal: 1000.00
Tax (8%): 80.00
Total Amount: 1080.00

Bank Details: Maybank, Account 1234567890
Thank you for your business.
"""

INVOICE_WRONG_TOTAL = """\
Global Supplies Sdn Bhd
45 Industrial Park, Penang, Malaysia

INVOICE

Invoice Number: INV-2026-014
Invoice Date: 2026-06-05
Due Date: 2026-06-25
Payment Terms: Net 20
Currency: MYR

Bill To: XYZ Company

Description                Qty   Unit Price   Amount
Office supplies bundle      2      500.00     1000.00
Delivery fee                 1       50.00       50.00

Subtotal: 1050.00
Tax (6%): 63.00
Total Amount: 1200.00

Bank Details: CIMB Bank, Account 9876543210
"""

INVOICE_MISSING_DUE_DATE = """\
TechWave Solutions
8 Innovation Drive, Cyberjaya, Malaysia

INVOICE

Invoice Number: INV-2026-027
Invoice Date: 2026-06-12
Payment Terms: Due upon receipt
Currency: MYR

Bill To: XYZ Company

Description                Qty   Unit Price   Amount
Cloud hosting (June)        1      450.00      450.00
Support retainer             1      150.00      150.00

Subtotal: 600.00
Tax (0%): 0.00
Total Amount: 600.00
"""

RECEIPT = """\
Grab
Transport Receipt

Receipt Number: RCP-1001
Transaction Date: 2026-06-12
Payment Method: Card (Visa ****1234)
Currency: MYR

Item                         Amount
GrabCar - KLCC to KLIA        43.40

Tax: 2.50
Total Amount: 45.90

Thank you for riding with Grab.
"""

PURCHASE_ORDER = """\
XYZ Company
Procurement Department

PURCHASE ORDER

PO Number: PO-2026-009
Buyer: XYZ Company
Supplier: ABC Vendor
Order Date: 2026-06-11
Delivery Date: 2026-06-20
Currency: MYR

Description                Qty   Unit Price   Amount
Laptop stands               10       80.00      800.00
Wireless keyboards          10      120.00     1200.00
Monitor arms                10       50.00      500.00

Total Amount: 2500.00

Please deliver to the address on file. Reference this PO number on the invoice.
"""

CONTRACT = """\
SERVICE AGREEMENT

This Service Agreement ("Agreement") is entered into between:

Party A: Company A Sdn Bhd ("Service Provider")
Party B: Company B Sdn Bhd ("Client")

Effective Date: 2026-06-01
End Date: 2027-06-01

1. Services
The Service Provider agrees to provide ongoing IT support and maintenance
services as described in Schedule A.

2. Payment Terms
The Client shall pay the Service Provider a monthly fee of MYR 5,000,
payable within 14 days of invoice date.

3. Obligations
The Service Provider shall maintain system uptime of at least 99% and
respond to support tickets within 4 business hours. The Client shall
provide timely access to systems and personnel as needed.

4. Termination
Either party may terminate this Agreement with 30 days' written notice.
Early termination by the Client before the End Date may incur an early
termination fee equal to one month's service fee.

5. Liability
The Service Provider's liability under this Agreement is limited to the
fees paid in the preceding three months. Neither party shall be liable
for indirect or consequential damages.
"""


# Maps scenario key -> {filename, expected_document_type, text}
# expected_document_type values match app.models.DocumentType.
DEMO_SCENARIOS: dict[str, dict] = {
    "invoice_clean": {
        "filename": "invoice_clean.pdf",
        "expected_document_type": "invoice",
        "text": INVOICE_CLEAN,
    },
    "invoice_wrong_total": {
        "filename": "invoice_wrong_total.pdf",
        "expected_document_type": "invoice",
        "text": INVOICE_WRONG_TOTAL,
    },
    "invoice_missing_due_date": {
        "filename": "invoice_missing_due_date.pdf",
        "expected_document_type": "invoice",
        "text": INVOICE_MISSING_DUE_DATE,
    },
    "receipt": {
        "filename": "receipt_grab.pdf",
        "expected_document_type": "receipt",
        "text": RECEIPT,
    },
    "purchase_order": {
        "filename": "purchase_order.pdf",
        "expected_document_type": "purchase_order",
        "text": PURCHASE_ORDER,
    },
    "contract": {
        "filename": "service_agreement.pdf",
        "expected_document_type": "contract",
        "text": CONTRACT,
    },
}

DEFAULT_SCENARIO = "invoice_clean"

# Prefix used in Document.notes to tag a document with a demo scenario,
# e.g. notes="demo_scenario:invoice_wrong_total"
SCENARIO_NOTE_PREFIX = "demo_scenario:"


def get_scenario_text(scenario_key: str) -> str:
    """Return the sample extracted text for a scenario key, defaulting to
    invoice_clean if the key is unrecognized."""
    scenario = DEMO_SCENARIOS.get(scenario_key, DEMO_SCENARIOS[DEFAULT_SCENARIO])
    return scenario["text"]
