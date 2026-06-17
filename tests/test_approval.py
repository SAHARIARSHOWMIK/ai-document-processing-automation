"""
Approval tests: user can approve valid document, reject, edit fields,
edited fields are saved, document with serious error cannot be approved
unless fixed.
"""


def _process_to_review(client, document_id):
    client.post(f"/documents/{document_id}/extract")
    client.post(f"/documents/{document_id}/classify")
    client.post(f"/documents/{document_id}/extract-fields")
    client.post(f"/documents/{document_id}/validate")


def test_user_can_approve_valid_document(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_clean.pdf")

    _process_to_review(client, doc["id"])

    response = client.post(f"/documents/{doc['id']}/approve")
    assert response.status_code == 200
    body = response.json()
    assert body["document"]["status"] == "approved"
    assert body["approval"]["status"] == "approved"
    assert body["approval"]["final_data"] is not None


def test_user_can_reject_document(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "receipt_grab.pdf")

    _process_to_review(client, doc["id"])

    response = client.post(f"/documents/{doc['id']}/reject", json={"reviewer_note": "Not needed"})
    assert response.status_code == 200
    body = response.json()
    assert body["document"]["status"] == "rejected"
    assert body["approval"]["reviewer_note"] == "Not needed"


def test_user_can_edit_fields(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_wrong_total.pdf")

    _process_to_review(client, doc["id"])

    extracted = client.get(f"/documents/{doc['id']}/extracted-data").json()
    fields = dict(extracted["extracted_fields"])
    fields["total_amount"] = 1113.0  # corrected to match subtotal + tax

    response = client.patch(f"/documents/{doc['id']}/fields", json={"fields": fields})
    assert response.status_code == 200
    assert response.json()["document"]["validation_result"]["status"] == "valid"


def test_edited_fields_are_saved(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_wrong_total.pdf")

    _process_to_review(client, doc["id"])

    extracted = client.get(f"/documents/{doc['id']}/extracted-data").json()
    fields = dict(extracted["extracted_fields"])
    fields["total_amount"] = 1113.0

    client.patch(f"/documents/{doc['id']}/fields", json={"fields": fields})

    updated = client.get(f"/documents/{doc['id']}/extracted-data").json()
    assert updated["extracted_fields"]["total_amount"] == 1113.0

    approval = client.get(f"/documents/{doc['id']}/approval").json()
    assert "total_amount" in approval["edited_fields"]
    assert approval["edited_fields"]["total_amount"]["old"] == 1200.0
    assert approval["edited_fields"]["total_amount"]["new"] == 1113.0


def test_document_with_error_cannot_be_approved_until_fixed(client):
    files = {"file": ("blank_invoice.pdf", b"not much here")}
    upload = client.post("/documents/upload", files=files)
    document_id = upload.json()["document"]["id"]

    client.post(f"/documents/{document_id}/extract")
    client.post(f"/documents/{document_id}/classify")
    client.post(f"/documents/{document_id}/extract-fields")

    empty_fields = {"vendor_name": None, "invoice_number": None, "invoice_date": None, "total_amount": None}
    client.patch(f"/documents/{document_id}/fields", json={"fields": empty_fields})

    # Should be blocked - validation status is 'failed'
    blocked = client.post(f"/documents/{document_id}/approve")
    assert blocked.status_code == 400

    # Fix the fields
    good_fields = {
        "vendor_name": "Test Vendor",
        "invoice_number": "INV-FIX-001",
        "invoice_date": "2026-06-01",
        "total_amount": 500.0,
    }
    client.patch(f"/documents/{document_id}/fields", json={"fields": good_fields})

    # Now approval should succeed
    approved = client.post(f"/documents/{document_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["document"]["status"] == "approved"


def test_rejected_document_cannot_be_approved_afterward(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "receipt_grab.pdf")

    _process_to_review(client, doc["id"])
    client.post(f"/documents/{doc['id']}/reject")

    blocked = client.post(f"/documents/{doc['id']}/approve")
    assert blocked.status_code == 400


def test_request_correction_then_edit_returns_to_pending_review(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_clean.pdf")

    _process_to_review(client, doc["id"])

    response = client.post(f"/documents/{doc['id']}/request-correction")
    assert response.status_code == 200
    assert response.json()["document"]["status"] == "needs_correction"

    extracted = client.get(f"/documents/{doc['id']}/extracted-data").json()
    fields = dict(extracted["extracted_fields"])

    edit_response = client.patch(f"/documents/{doc['id']}/fields", json={"fields": fields})
    assert edit_response.json()["document"]["status"] == "pending_review"
