"""
Audit log tests: upload/extraction/validation/approval/export events are
all recorded, and the full chain is traceable for a single document.
"""


def test_full_chain_is_recorded_in_audit_log(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_clean.pdf")
    document_id = doc["id"]

    client.post(f"/documents/{document_id}/extract")
    client.post(f"/documents/{document_id}/classify")
    client.post(f"/documents/{document_id}/extract-fields")
    client.post(f"/documents/{document_id}/validate")
    client.post(f"/documents/{document_id}/approve")
    client.post("/export/json", json={"document_ids": [document_id]})

    logs = client.get("/audit-logs", params={"document_id": document_id}).json()
    event_types = {log["event_type"] for log in logs}

    expected = {
        "document_uploaded",
        "text_extracted",
        "document_classified",
        "fields_extracted",
        "validation_completed",
        "document_approved",
        "export_completed",
    }
    assert expected.issubset(event_types)


def test_upload_event_recorded(client):
    files = {"file": ("invoice.pdf", b"content")}
    upload = client.post("/documents/upload", files=files)
    document_id = upload.json()["document"]["id"]

    logs = client.get("/audit-logs", params={"document_id": document_id}).json()
    assert any(log["event_type"] == "document_uploaded" for log in logs)


def test_extraction_event_recorded(client):
    files = {"file": ("invoice.pdf", b"content")}
    upload = client.post("/documents/upload", files=files)
    document_id = upload.json()["document"]["id"]
    client.post(f"/documents/{document_id}/extract")

    logs = client.get("/audit-logs", params={"document_id": document_id}).json()
    assert any(log["event_type"] == "text_extracted" for log in logs)


def test_validation_warning_event_recorded(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_wrong_total.pdf")

    client.post(f"/documents/{doc['id']}/extract")
    client.post(f"/documents/{doc['id']}/classify")
    client.post(f"/documents/{doc['id']}/extract-fields")
    client.post(f"/documents/{doc['id']}/validate")

    logs = client.get("/audit-logs", params={"document_id": doc["id"]}).json()
    assert any(log["event_type"] == "validation_warning" for log in logs)


def test_approval_event_recorded(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_clean.pdf")

    client.post(f"/documents/{doc['id']}/extract")
    client.post(f"/documents/{doc['id']}/classify")
    client.post(f"/documents/{doc['id']}/extract-fields")
    client.post(f"/documents/{doc['id']}/validate")
    client.post(f"/documents/{doc['id']}/approve")

    logs = client.get("/audit-logs", params={"document_id": doc["id"]}).json()
    assert any(log["event_type"] == "document_approved" and log["actor"] == "user" for log in logs)


def test_export_event_recorded(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_clean.pdf")

    client.post(f"/documents/{doc['id']}/extract")
    client.post(f"/documents/{doc['id']}/classify")
    client.post(f"/documents/{doc['id']}/extract-fields")
    client.post(f"/documents/{doc['id']}/validate")
    client.post(f"/documents/{doc['id']}/approve")
    client.post("/export/csv", json={"document_ids": [doc["id"]]})

    logs = client.get("/audit-logs", params={"document_id": doc["id"]}).json()
    assert any(log["event_type"] == "export_completed" for log in logs)


def test_dashboard_metrics_reflect_pipeline_state(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_clean.pdf")

    metrics = client.get("/dashboard/metrics").json()
    assert metrics["total_documents"] == 6

    client.post(f"/documents/{doc['id']}/extract")
    client.post(f"/documents/{doc['id']}/classify")
    client.post(f"/documents/{doc['id']}/extract-fields")
    client.post(f"/documents/{doc['id']}/validate")

    metrics = client.get("/dashboard/metrics").json()
    assert metrics["pending_review"] == 1

    client.post(f"/documents/{doc['id']}/approve")
    metrics = client.get("/dashboard/metrics").json()
    assert metrics["approved_documents"] == 1
    assert metrics["pending_review"] == 0
