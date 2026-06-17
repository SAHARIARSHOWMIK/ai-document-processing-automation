"""
Upload tests: PDF/image upload works, unsupported/empty/large files are rejected.
"""

from tests.conftest import upload_demo_text_file


def test_pdf_upload_works(client):
    response = upload_demo_text_file(client, "invoice.pdf", content="%PDF-1.4 fake pdf content")
    assert response.status_code == 200
    body = response.json()
    assert body["document"]["filename"] == "invoice.pdf"
    assert body["document"]["file_type"] == "pdf"
    assert body["document"]["status"] == "uploaded"


def test_image_upload_works(client):
    response = upload_demo_text_file(client, "receipt.png", content="fake png bytes")
    assert response.status_code == 200
    body = response.json()
    assert body["document"]["file_type"] == "png"


def test_unsupported_file_type_is_rejected(client):
    response = upload_demo_text_file(client, "malware.exe", content="not allowed")
    assert response.status_code == 415

    # No document should have been created
    documents = client.get("/documents").json()
    assert documents == []


def test_empty_file_is_rejected(client):
    response = upload_demo_text_file(client, "empty.pdf", content="")
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_large_file_is_rejected(client):
    # MAX_UPLOAD_SIZE_MB defaults to 10; generate something larger.
    big_content = "x" * (11 * 1024 * 1024)
    response = upload_demo_text_file(client, "huge.pdf", content=big_content)
    assert response.status_code == 413


def test_upload_with_expected_type_and_notes(client):
    files = {"file": ("invoice.pdf", b"%PDF-1.4 fake")}
    data = {"expected_document_type": "invoice", "notes": "from accounting team"}
    response = client.post("/documents/upload", files=files, data=data)
    assert response.status_code == 200
    body = response.json()["document"]
    assert body["expected_document_type"] == "invoice"
    assert body["notes"] == "from accounting team"


def test_duplicate_filename_is_allowed_but_logged(client):
    upload_demo_text_file(client, "invoice.pdf", content="first version")
    second = upload_demo_text_file(client, "invoice.pdf", content="second version")
    assert second.status_code == 200

    documents = client.get("/documents").json()
    assert len(documents) == 2

    logs = client.get("/audit-logs").json()
    event_types = {log["event_type"] for log in logs}
    assert "duplicate_filename_detected" in event_types
