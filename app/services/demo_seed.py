"""
Demo seeding service.

Creates Document rows for the 6 sample scenarios in demo_documents.py,
without requiring an actual file upload - useful for the dashboard's
"Demo Mode" page and for quickly populating a fresh database for testing.

Each seeded document is tagged with `notes="demo_scenario:<key>"` so
text_extraction.mock_extract resolves to the correct canned sample text
regardless of DEMO_MODE (is_demo=True forces the mock path either way).
"""

from sqlalchemy.orm import Session

from app.models import Document, DocumentStatus
from app.services.audit import log_event
from app.services.demo_documents import DEMO_SCENARIOS, SCENARIO_NOTE_PREFIX


def seed_demo_documents(db: Session, scenario_keys: list[str] | None = None) -> list[Document]:
    """Create Document rows for the given demo scenarios (all 6 by default).

    Skips scenarios that have already been seeded (matched by filename) so
    this is safe to call multiple times without creating duplicates.
    """
    keys = scenario_keys or list(DEMO_SCENARIOS.keys())

    created: list[Document] = []
    for key in keys:
        scenario = DEMO_SCENARIOS.get(key)
        if not scenario:
            continue

        existing = db.query(Document).filter(Document.filename == scenario["filename"]).first()
        if existing:
            continue

        document = Document(
            filename=scenario["filename"],
            file_type="pdf",
            file_path=f"(demo:{key})",  # no real file on disk for seeded demo docs
            file_size_bytes=len(scenario["text"].encode("utf-8")),
            status=DocumentStatus.UPLOADED,
            expected_document_type=scenario["expected_document_type"],
            notes=f"{SCENARIO_NOTE_PREFIX}{key}",
            is_demo=True,
        )
        db.add(document)
        db.commit()
        db.refresh(document)

        log_event(
            db,
            event_type="document_uploaded",
            message=f"Demo document '{scenario['filename']}' seeded (scenario={key}).",
            document_id=document.id,
            details={"demo_scenario": key},
        )

        created.append(document)

    return created
