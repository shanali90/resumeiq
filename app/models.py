"""SQLAlchemy ORM models with at-rest field-level encryption for resumes and matches."""

from __future__ import annotations

import datetime
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.db import Base
from app.security import encrypt_text, decrypt_text


class ResumeModel(Base):
    """Stored resume analysis with encrypted PII and raw text at rest."""
    __tablename__ = "resumes"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    _candidate_name = Column("candidate_name", String(512), nullable=True)
    _raw_text = Column("raw_text", Text, nullable=False)
    _profile_json = Column("profile_json", Text, nullable=False)
    quality_json = Column(Text, nullable=False)
    skills_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))

    matches = relationship("MatchModel", back_populates="resume", cascade="all, delete-orphan")

    # Encrypted properties
    @property
    def candidate_name(self) -> str | None:
        return decrypt_text(self._candidate_name)

    @candidate_name.setter
    def candidate_name(self, value: str | None) -> None:
        self._candidate_name = encrypt_text(value)

    @property
    def raw_text(self) -> str:
        return decrypt_text(self._raw_text) or ""

    @raw_text.setter
    def raw_text(self, value: str) -> None:
        self._raw_text = encrypt_text(value) or ""

    @property
    def profile_json(self) -> str:
        return decrypt_text(self._profile_json) or "{}"

    @profile_json.setter
    def profile_json(self, value: str) -> None:
        self._profile_json = encrypt_text(value) or "{}"


class JobModel(Base):
    """Stored job description."""
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=True)
    raw_text = Column(Text, nullable=False)
    jd_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))

    matches = relationship("MatchModel", back_populates="job", cascade="all, delete-orphan")


class MatchModel(Base):
    """Stored match result between a resume and a job."""
    __tablename__ = "matches"

    id = Column(Integer, primary_key=True, index=True)
    resume_id = Column(Integer, ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    overall_score = Column(Float, nullable=False)
    verdict = Column(String(50), nullable=False)
    match_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))

    resume = relationship("ResumeModel", back_populates="matches")
    job = relationship("JobModel", back_populates="matches")
