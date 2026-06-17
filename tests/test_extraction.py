"""
Text extraction tests: demo/mock extraction succeeds and tags the right
method/status; extraction is stored and retrievable.

Real PDF/OCR extraction (pdfplumber/pytesseract) is exercised in
test_real_extraction.py, skipped automatically if those libraries or the
tesseract binary aren't available in the environment.
"""

from tests.conftest import upload_demo_text_file


def test_mock_extraction_succeeds_and_stores_method(client):
    upload = upload_demo_text_file(client, "invoice_clean.pdf")
    document_id = upload.json()["document"]["id"]

    response = client.post(f"/documents/{document_id}/extract")
    assert response.status_code == 200
    body = response.json()

    assert body["extraction_status"] == "success"
    assert body["extraction_method"] == "mock"
    assert len(body["raw_text"]) > 0


def test_extraction_updates_document_status(client):
    upload = upload_demo_text_file(client, "invoice_clean.pdf")
    document_id = upload.json()["document"]["id"]

    client.post(f"/documents/{document_id}/extract")

    document = client.get(f"/documents/{document_id}").json()
    assert document["status"] == "text_extracted"


def test_extracted_text_is_retrievable(client):
    upload = upload_demo_text_file(client, "invoice_clean.pdf")
    document_id = upload.json()["document"]["id"]

    client.post(f"/documents/{document_id}/extract")
    response = client.get(f"/documents/{document_id}/extracted-text")
    assert response.status_code == 200
    assert response.json()["extraction_status"] == "success"


def test_extracted_text_404_before_extraction(client):
    upload = upload_demo_text_file(client, "invoice_clean.pdf")
    document_id = upload.json()["document"]["id"]

    response = client.get(f"/documents/{document_id}/extracted-text")
    assert response.status_code == 404


def test_seeded_demo_document_extracts_correct_scenario_text(seeded_client):
    client = seeded_client
    documents = client.get("/documents").json()
    wrong_total_doc = next(d for d in documents if d["filename"] == "invoice_wrong_total.pdf")

    response = client.post(f"/documents/{wrong_total_doc['id']}/extract")
    assert response.status_code == 200
    text = response.json()["raw_text"]

    assert "INV-2026-014" in text
    assert "Global Supplies" in text
