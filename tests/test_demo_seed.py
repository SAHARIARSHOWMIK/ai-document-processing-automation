"""
Demo seeding tests: seed data works correctly and is idempotent.
"""


def test_seed_creates_six_documents(client):
    response = client.post("/demo/seed")
    assert response.status_code == 200
    documents = response.json()
    assert len(documents) == 6

    filenames = {d["filename"] for d in documents}
    assert filenames == {
        "invoice_clean.pdf",
        "invoice_wrong_total.pdf",
        "invoice_missing_due_date.pdf",
        "receipt_grab.pdf",
        "purchase_order.pdf",
        "service_agreement.pdf",
    }


def test_seed_is_idempotent(client):
    first = client.post("/demo/seed").json()
    second = client.post("/demo/seed").json()

    assert len(first) == 6
    assert len(second) == 0  # already seeded, nothing new created

    all_docs = client.get("/documents").json()
    assert len(all_docs) == 6


def test_seeded_documents_are_marked_demo(seeded_client):
    documents = seeded_client.get("/documents").json()
    assert all(d["is_demo"] for d in documents)
