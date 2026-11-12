"""Database setup — SQLAlchemy engine, session factory, dependency, and auto-purge."""

from __future__ import annotations

import datetime
import logging
import os
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Use /tmp on Linux/HuggingFace if default sqlite path is used or if in production
db_url = settings.database_url
if os.name != "nt" and ("./resumeiq.db" in db_url or db_url == "sqlite:///resumeiq.db"):
    db_url = "sqlite:////tmp/resumeiq.db"

engine = create_engine(
    db_url,
    connect_args={"check_same_thread": False} if "sqlite" in db_url else {},
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """Dependency for providing a transactional database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Initialize database tables and run cleanup."""
    import app.models  # Ensure models are registered
    Base.metadata.create_all(bind=engine)
    logger.info("Initialized database tables at %s", db_url)
    cleanup_old_records(hours=settings.auto_purge_hours)


def cleanup_old_records(hours: int = 24) -> int:
    """Auto-purge resumes and matches older than `hours` (privacy compliance)."""
    from app.models import ResumeModel, MatchModel, JobModel

    cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
    purged_count = 0

    with SessionLocal() as db:
        try:
            # Delete old matches first
            old_matches = db.query(MatchModel).filter(MatchModel.created_at < cutoff).all()
            for m in old_matches:
                db.delete(m)
                purged_count += 1

            # Delete old resumes
            old_resumes = db.query(ResumeModel).filter(ResumeModel.created_at < cutoff).all()
            for r in old_resumes:
                db.delete(r)
                purged_count += 1

            if purged_count > 0:
                db.commit()
                logger.info("Auto-purged %d records older than %d hours.", purged_count, hours)
        except Exception as exc:
            db.rollback()
            logger.warning("Auto-purge failed: %s", exc)

    return purged_count
