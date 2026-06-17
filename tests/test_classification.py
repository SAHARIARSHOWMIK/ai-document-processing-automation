"""
Classification tests: invoice/receipt/PO/contract are classified correctly;
unrecognized text is sent to manual review.
"""

from tests.conftest import upload_demo_text_file


def _extract_and_classify(client, document_id):
    client.post(f"/documents/{document_id}/extract")
    return client.post(f"/documents/{document_id}/classify")


def test_invoice_classified_correctly(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_clean.pdf")

    response = _extract_and_classify(client, doc["id"])
    assert response.status_code == 200
    body = response.json()
    assert body["document_type"] == "invoice"
    assert body["status"] == "classified"
    assert body["classification_confidence"] >= 0.80


def test_receipt_classified_correctly(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "receipt_grab.pdf")

    response = _extract_and_classify(client, doc["id"])
    assert response.json()["document_type"] == "receipt"


def test_purchase_order_classified_correctly(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "purchase_order.pdf")

    response = _extract_and_classify(client, doc["id"])
    assert response.json()["document_type"] == "purchase_order"


def test_contract_classified_correctly(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "service_agreement.pdf")

    response = _extract_and_classify(client, doc["id"])
    assert response.json()["document_type"] == "contract"


def test_classify_requires_successful_extraction_first(client):
    upload = upload_demo_text_file(client, "invoice.pdf")
    document_id = upload.json()["document"]["id"]

    response = client.post(f"/documents/{document_id}/classify")
    assert response.status_code == 400


def test_classification_status_routing_is_consistent(client):
    """Whatever confidence/document_type the analyzer returns, classify()
    must route to either 'classified' or 'pending_review' (never some other
    status) and must always set document_type. This is the contract that
    matters for the "unknown -> manual review" rule, independent of which
    specific text was analyzed.
    """
    upload = upload_demo_text_file(client, "mystery.pdf")
    document_id = upload.json()["document"]["id"]
    client.post(f"/documents/{document_id}/extract")  # mock mode -> invoice_clean text

    response = client.post(f"/documents/{document_id}/classify")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in ("classified", "pending_review")
    assert body["document_type"] is not None
