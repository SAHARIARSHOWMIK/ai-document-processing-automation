"""
Database engine and session management.

Supports both SQLite (default, zero-setup, used for demo/local dev)
and PostgreSQL (set DATABASE_URL to a postgresql:// URL).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

# SQLite needs this connect_arg when used with multiple threads (FastAPI/Streamlit).
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a database session and closes it afterwards."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables. Safe to call multiple times (no-op if tables exist)."""
    # Import models here so they are registered on Base before create_all runs.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
