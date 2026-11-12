"""ResumeIQ configuration — single source of truth for all settings.
Supports local execution and production deployment to Hugging Face Spaces.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    # --- Environment & Ports ---
    app_env: str = Field(default="production", alias="APP_ENV")
    api_host: str = Field(default="127.0.0.1", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    streamlit_port: int = Field(default=7860, alias="STREAMLIT_PORT")

    # --- Access Control ---
    app_access_password: str = Field(default="", alias="APP_ACCESS_PASSWORD")

    # --- Gemini LLM ---
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.0-flash", alias="GEMINI_MODEL")
    gemini_daily_limit: int = Field(default=50, alias="GEMINI_DAILY_LIMIT")

    # --- Database & Encryption ---
    database_url: str = Field(default="sqlite:///./resumeiq.db", alias="DATABASE_URL")
    data_encryption_key: str = Field(default="", alias="DATA_ENCRYPTION_KEY")
    auto_purge_hours: int = Field(default=24, alias="AUTO_PURGE_HOURS")

    # --- Upload & File Security ---
    max_file_size_mb: int = Field(default=5, alias="MAX_FILE_SIZE_MB")
    max_pdf_pages: int = Field(default=10, alias="MAX_PDF_PAGES")
    max_docx_paragraphs: int = Field(default=500, alias="MAX_DOCX_PARAGRAPHS")
    max_docx_uncompressed_mb: int = Field(default=20, alias="MAX_DOCX_UNCOMPRESSED_MB")
    allowed_extensions: set[str] = {".pdf", ".docx"}
    allowed_content_types: set[str] = {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }

    # --- Paths ---
    base_dir: Path = Path(__file__).resolve().parent.parent
    data_dir: Path = Path(__file__).resolve().parent / "data"
    taxonomy_path: Path = Path(__file__).resolve().parent / "data" / "skills_taxonomy.json"

    # --- Logging ---
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # --- Matching weights (must sum to 1.0) ---
    weight_required_skills: float = 0.40
    weight_semantic_similarity: float = 0.20
    weight_preferred_skills: float = 0.10
    weight_experience_fit: float = 0.20
    weight_education_fit: float = 0.10

    # --- Scoring thresholds ---
    fuzzy_match_threshold: int = 90
    scanned_pdf_min_chars: int = 50

    # --- Verdict bands ---
    verdict_strong: int = 80
    verdict_good: int = 65
    verdict_partial: int = 45

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.app_env.lower() in ("production", "prod")

    @property
    def has_gemini_key(self) -> bool:
        """Check if a valid non-empty Gemini API key is configured."""
        k = self.gemini_api_key.strip()
        return bool(k and k != "your_gemini_api_key_here")

    @property
    def max_file_size_bytes(self) -> int:
        """Maximum file size in bytes."""
        return self.max_file_size_mb * 1024 * 1024

    @property
    def max_docx_uncompressed_bytes(self) -> int:
        """Maximum safe uncompressed DOCX bytes."""
        return self.max_docx_uncompressed_mb * 1024 * 1024


def _sync_streamlit_secrets() -> None:
    """Read configuration from Streamlit secrets if available and sync to os.environ."""
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            keys = [
                "GEMINI_API_KEY",
                "GEMINI_MODEL",
                "GEMINI_DAILY_LIMIT",
                "APP_ACCESS_PASSWORD",
                "DATA_ENCRYPTION_KEY",
                "APP_ENV",
                "API_HOST",
                "API_PORT",
            ]
            for key in keys:
                if key not in os.environ and key in st.secrets:
                    val = str(st.secrets[key]).strip()
                    if val:
                        os.environ[key] = val
                elif key not in os.environ and key.lower() in st.secrets:
                    val = str(st.secrets[key.lower()]).strip()
                    if val:
                        os.environ[key] = val
    except Exception:
        pass


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton, synchronizing Streamlit secrets if present."""
    _sync_streamlit_secrets()
    return Settings()
