"""
Validation tests: total calculation passes/fails, missing field creates
error, due-date-before-invoice-date creates error, duplicate invoice
creates warning, invalid currency creates warning.
"""


def _process_to_validation(client, document_id):
    client.post(f"/documents/{document_id}/extract")
    client.post(f"/documents/{document_id}/classify")
    client.post(f"/documents/{document_id}/extract-fields")
    return client.post(f"/documents/{document_id}/validate")


def test_clean_invoice_total_calculation_passes(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_clean.pdf")

    response = _process_to_validation(client, doc["id"])
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "valid"
    assert not any(i["level"] == "error" for i in body["issues"])


def test_total_mismatch_creates_warning(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_wrong_total.pdf")

    response = _process_to_validation(client, doc["id"])
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "warning"
    amount_issues = [i for i in body["issues"] if i["rule"] == "amount_validation"]
    assert any("does not match" in i["message"] for i in amount_issues)


def test_missing_due_date_creates_warning(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_missing_due_date.pdf")

    response = _process_to_validation(client, doc["id"])
    assert response.status_code == 200
    body = response.json()
    due_date_issues = [i for i in body["issues"] if i.get("field") == "due_date"]
    assert len(due_date_issues) == 1
    assert due_date_issues[0]["level"] == "warning"


def test_missing_required_field_creates_error(client):
    """An uploaded (non-demo) document with minimal/garbage text should be
    missing required invoice fields, producing validation errors."""
    files = {"file": ("blank_invoice.pdf", b"not much here")}
    upload = client.post("/documents/upload", files=files)
    document_id = upload.json()["document"]["id"]

    client.post(f"/documents/{document_id}/extract")
    client.post(f"/documents/{document_id}/classify")
    # Mock mode always resolves to a default scenario for non-seeded
    # documents, so to directly test the "missing required field" error
    # path we manually correct fields to a clearly invalid state and
    # re-validate, which is the more realistic path a reviewer would hit.
    client.post(f"/documents/{document_id}/extract-fields")

    empty_fields = {"vendor_name": None, "invoice_number": None, "invoice_date": None, "total_amount": None}
    patch_response = client.patch(f"/documents/{document_id}/fields", json={"fields": empty_fields})
    assert patch_response.status_code == 200

    validation = patch_response.json()["document"]["validation_result"]
    assert validation["status"] == "failed"
    error_fields = {i["field"] for i in validation["issues"] if i["level"] == "error"}
    assert {"vendor_name", "invoice_number", "invoice_date", "total_amount"}.issubset(error_fields)


def test_due_date_before_invoice_date_creates_error(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_clean.pdf")

    client.post(f"/documents/{doc['id']}/extract")
    client.post(f"/documents/{doc['id']}/classify")
    client.post(f"/documents/{doc['id']}/extract-fields")

    extracted = client.get(f"/documents/{doc['id']}/extracted-data").json()
    fields = dict(extracted["extracted_fields"])
    fields["due_date"] = "2026-01-01"  # before invoice_date 2026-06-10

    response = client.patch(f"/documents/{doc['id']}/fields", json={"fields": fields})
    assert response.status_code == 200
    validation = response.json()["document"]["validation_result"]
    assert validation["status"] == "failed"
    assert any(i["rule"] == "date_validation" and i["level"] == "error" for i in validation["issues"])


def test_duplicate_invoice_creates_warning(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_clean.pdf")

    client.post(f"/documents/{doc['id']}/extract")
    client.post(f"/documents/{doc['id']}/classify")
    client.post(f"/documents/{doc['id']}/extract-fields")
    client.post(f"/documents/{doc['id']}/validate")

    # Upload a second document with identical vendor+invoice_number fields.
    files = {"file": ("invoice_clean_copy.pdf", b"copy")}
    upload = client.post("/documents/upload", files=files, data={"notes": "demo_scenario:invoice_clean"})
    second_id = upload.json()["document"]["id"]
    client.post(f"/documents/{second_id}/extract")
    client.post(f"/documents/{second_id}/classify")
    response = client.post(f"/documents/{second_id}/extract-fields")
    assert response.status_code == 200

    validation_response = client.post(f"/documents/{second_id}/validate")
    body = validation_response.json()
    duplicate_issues = [i for i in body["issues"] if i["rule"] == "duplicate_validation"]
    assert len(duplicate_issues) == 1
    assert duplicate_issues[0]["level"] == "warning"


def test_invalid_currency_creates_warning(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    doc = next(d for d in documents if d["filename"] == "invoice_clean.pdf")

    client.post(f"/documents/{doc['id']}/extract")
    client.post(f"/documents/{doc['id']}/classify")
    client.post(f"/documents/{doc['id']}/extract-fields")

    extracted = client.get(f"/documents/{doc['id']}/extracted-data").json()
    fields = dict(extracted["extracted_fields"])
    fields["currency"] = "XYZ"  # not in VALID_CURRENCIES

    response = client.patch(f"/documents/{doc['id']}/fields", json={"fields": fields})
    validation = response.json()["document"]["validation_result"]
    currency_issues = [i for i in validation["issues"] if i["rule"] == "currency_validation"]
    assert any(i["level"] == "warning" for i in currency_issues)
