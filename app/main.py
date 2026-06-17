"""
Application entrypoint.

Run locally with:
    uvicorn app.main:app --reload

On startup, tables are created automatically (init_db) and the upload/export
directories are created if missing.
"""

import logging
import os

from fastapi import FastAPI, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import init_db, get_db
from app.schemas import HealthResponse
from app.routers import documents, extraction, ai, validation, review, export, dashboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("doc_automation")

app = FastAPI(
    title=settings.app_name,
    description=(
        "An AI system that takes business documents (invoices, receipts, "
        "purchase orders, contracts), extracts text, classifies the document "
        "type, extracts structured fields, validates them against business "
        "rules, and only exports data after human approval. "
        "AI recommends. Validation checks. Human approves. System exports."
    ),
    version="0.1.0",
)


@app.on_event("startup")
def on_startup():
    logger.info("Starting %s (env=%s, demo_mode=%s)", settings.app_name, settings.env, settings.demo_mode)
    init_db()
    os.makedirs(settings.upload_dir, exist_ok=True)
    os.makedirs(settings.export_dir, exist_ok=True)
    logger.info("Database initialized at %s", settings.database_url)
    logger.info("Upload dir: %s | Export dir: %s", settings.upload_dir, settings.export_dir)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health_check(db: Session = Depends(get_db)):
    """Basic health/status endpoint."""
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    return HealthResponse(
        status="ok" if db_ok else "degraded",
        app_name=settings.app_name,
        env=settings.env,
        demo_mode=settings.demo_mode,
        database_connected=db_ok,
    )


@app.get("/", tags=["system"])
def root():
    return {
        "message": f"{settings.app_name} is running.",
        "docs": "/docs",
        "health": "/health",
    }


app.include_router(documents.router)
app.include_router(extraction.router)
app.include_router(ai.router)
app.include_router(validation.router)
app.include_router(review.router)
app.include_router(export.router)
app.include_router(dashboard.router)
