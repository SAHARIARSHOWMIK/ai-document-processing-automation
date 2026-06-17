"""
Export tests: approved document can export, rejected/pending documents
cannot export, export log is created.
"""


def _process_and_approve(client, document_id):
    client.post(f"/documents/{document_id}/extract")
    client.post(f"/documents/{document_id}/classify")
    client.post(f"/documents/{document_id}/extract-fields")
    client.post(f"/documents/{document_id}/validate")
    client.post(f"/documents/{document_id}/approve")


def test_approved_document_can_export_csv(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_clean.pdf")
    _process_and_approve(client, doc["id"])

    response = client.post("/export/csv", json={"document_ids": [doc["id"]]})
    assert response.status_code == 200
    body = response.json()
    assert body["export_log"]["export_status"] == "success"
    assert body["export_log"]["export_type"] == "csv"

    updated_doc = client.get(f"/documents/{doc['id']}").json()
    assert updated_doc["status"] == "exported"


def test_approved_document_can_export_json(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "purchase_order.pdf")
    _process_and_approve(client, doc["id"])

    response = client.post("/export/json", json={"document_ids": [doc["id"]]})
    assert response.status_code == 200
    assert response.json()["export_log"]["export_type"] == "json"


def test_rejected_document_cannot_export(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "receipt_grab.pdf")

    client.post(f"/documents/{doc['id']}/extract")
    client.post(f"/documents/{doc['id']}/classify")
    client.post(f"/documents/{doc['id']}/extract-fields")
    client.post(f"/documents/{doc['id']}/validate")
    client.post(f"/documents/{doc['id']}/reject")

    response = client.post("/export/csv", json={"document_ids": [doc["id"]]})
    assert response.status_code == 400


def test_pending_document_cannot_export(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_clean.pdf")

    client.post(f"/documents/{doc['id']}/extract")
    client.post(f"/documents/{doc['id']}/classify")
    client.post(f"/documents/{doc['id']}/extract-fields")
    client.post(f"/documents/{doc['id']}/validate")
    # No approval decision made - still pending_review

    response = client.post("/export/csv", json={"document_ids": [doc["id"]]})
    assert response.status_code == 400


def test_export_log_is_created_and_listed(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "service_agreement.pdf")
    _process_and_approve(client, doc["id"])

    client.post("/export/json", json={"document_ids": [doc["id"]]})

    logs = client.get("/export-logs", params={"document_id": doc["id"]}).json()
    assert len(logs) == 1
    assert logs[0]["export_status"] == "success"


def test_export_downloadable_file_contains_data(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_clean.pdf")
    _process_and_approve(client, doc["id"])

    export_response = client.post("/export/json", json={"document_ids": [doc["id"]]})
    log_id = export_response.json()["export_log"]["id"]

    download = client.get(f"/export/download/{log_id}")
    assert download.status_code == 200
    data = download.json()
    assert data[0]["document_id"] == doc["id"]
    assert data[0]["fields"]["invoice_number"] == "INV-2026-001"
