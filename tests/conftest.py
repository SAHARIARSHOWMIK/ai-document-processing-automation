"""
Shared pytest fixtures.

Tests run with:
  - DEMO_MODE=true (so no Tesseract/Anthropic credentials are needed - the
    mock text extractor and mock classifier/extractor are used)
  - An isolated in-memory SQLite database per test, via dependency override
    of `get_db`. Tests never touch the developer's app.db file.
  - A per-test temp directory for UPLOAD_DIR/EXPORT_DIR, so test runs never
    pollute (or depend on) the real ./uploads or ./exports folders.
"""

import os
import tempfile

# Must be set before app modules are imported, since Settings() is
# instantiated at import time in app/config.py.
os.environ["DEMO_MODE"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
_tmp_root = tempfile.mkdtemp(prefix="doc_automation_test_")
os.environ["UPLOAD_DIR"] = os.path.join(_tmp_root, "uploads")
os.environ["EXPORT_DIR"] = os.path.join(_tmp_root, "exports")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture()
def client():
    """A TestClient wired to a fresh in-memory SQLite database."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture()
def seeded_client(client):
    """A client that has already seeded the 6 demo documents."""
    response = client.post("/demo/seed")
    assert response.status_code == 200
    return client


def upload_demo_text_file(client, filename: str, content: str = "dummy content"):
    """Helper: upload a small in-memory file through the real upload endpoint
    (used by tests that need a *real* uploaded file, as opposed to a seeded
    demo document with no file on disk).
    """
    files = {"file": (filename, content.encode("utf-8"))}
    return client.post("/documents/upload", files=files)
