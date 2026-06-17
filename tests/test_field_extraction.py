"""
Field extraction tests: invoice/receipt/PO/contract fields are extracted;
missing/uncertain fields are listed.
"""


def _process_to_extraction(client, document_id):
    client.post(f"/documents/{document_id}/extract")
    client.post(f"/documents/{document_id}/classify")
    return client.post(f"/documents/{document_id}/extract-fields")


def test_invoice_fields_extracted(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_clean.pdf")

    response = _process_to_extraction(client, doc["id"])
    assert response.status_code == 200
    body = response.json()

    fields = body["extracted_fields"]
    assert fields["invoice_number"] == "INV-2026-001"
    assert fields["total_amount"] == 1080.0
    assert fields["due_date"] == "2026-06-30"
    assert body["missing_fields"] == []


def test_receipt_fields_extracted(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "receipt_grab.pdf")

    response = _process_to_extraction(client, doc["id"])
    assert response.status_code == 200
    fields = response.json()["extracted_fields"]
    assert fields["merchant_name"] == "Grab"
    assert fields["total_amount"] == 45.90


def test_po_fields_extracted(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "purchase_order.pdf")

    response = _process_to_extraction(client, doc["id"])
    assert response.status_code == 200
    fields = response.json()["extracted_fields"]
    assert fields["po_number"] == "PO-2026-009"
    assert fields["total_amount"] == 2500.0


def test_contract_fields_extracted(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "service_agreement.pdf")

    response = _process_to_extraction(client, doc["id"])
    assert response.status_code == 200
    fields = response.json()["extracted_fields"]
    assert "Company A" in fields["party_a"]
    assert "Company B" in fields["party_b"]
    assert fields["termination_clause"] is not None


def test_missing_fields_are_listed(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_missing_due_date.pdf")

    response = _process_to_extraction(client, doc["id"])
    assert response.status_code == 200
    body = response.json()
    assert body["extracted_fields"]["due_date"] is None


def test_extract_fields_requires_classification_first(client):
    files = {"file": ("invoice.pdf", b"some content")}
    upload = client.post("/documents/upload", files=files)
    document_id = upload.json()["document"]["id"]
    client.post(f"/documents/{document_id}/extract")

    response = client.post(f"/documents/{document_id}/extract-fields")
    assert response.status_code == 400
