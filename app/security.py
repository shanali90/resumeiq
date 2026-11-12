"""Security utilities for ResumeIQ.

Includes:
- Field-level at-rest database encryption via Fernet (symmetric AES-128-CBC / HMAC-SHA256).
- In-memory rate limiting per client IP / session.
- Gemini daily budget guard (prevents external quota drain, auto falls back to rule-based).
- DOCX zip-bomb and decompression bomb guards.
- Password authentication gate with constant-time comparison and lockout.
"""

from __future__ import annotations

import base64
import collections
import datetime
import hashlib
import hmac
import io
import logging
import os
import threading
import time
import zipfile
from typing import Optional

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

# ── 1. Database Field-Level Encryption (Fernet) ──────────────────────

_FERNET_INSTANCE: Optional[Fernet] = None
_FERNET_LOCK = threading.Lock()


def get_fernet() -> Fernet:
    """Return singleton Fernet instance.

    Uses DATA_ENCRYPTION_KEY if provided; otherwise generates an ephemeral key.
    """
    global _FERNET_INSTANCE
    with _FERNET_LOCK:
        if _FERNET_INSTANCE is None:
            raw_key = os.getenv("DATA_ENCRYPTION_KEY", "").strip()
            if raw_key:
                # Ensure 32-byte urlsafe base64
                try:
                    _FERNET_INSTANCE = Fernet(raw_key.encode("utf-8"))
                    logger.info("Fernet encryption initialized using DATA_ENCRYPTION_KEY.")
                except Exception as exc:
                    logger.warning("Invalid DATA_ENCRYPTION_KEY (%s). Generating ephemeral key.", exc)
                    _FERNET_INSTANCE = Fernet(Fernet.generate_key())
            else:
                logger.info("DATA_ENCRYPTION_KEY not set. Generating ephemeral Fernet key for session.")
                _FERNET_INSTANCE = Fernet(Fernet.generate_key())
        return _FERNET_INSTANCE


def encrypt_text(plain_text: Optional[str]) -> Optional[str]:
    """Encrypt a string at rest using Fernet."""
    if plain_text is None:
        return None
    if not plain_text:
        return ""
    f = get_fernet()
    encrypted_bytes = f.encrypt(plain_text.encode("utf-8"))
    return encrypted_bytes.decode("utf-8")


def decrypt_text(cipher_text: Optional[str]) -> Optional[str]:
    """Decrypt a string at rest using Fernet."""
    if cipher_text is None:
        return None
    if not cipher_text:
        return ""
    try:
        f = get_fernet()
        decrypted_bytes = f.decrypt(cipher_text.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except Exception as exc:
        logger.error("Fernet decryption error: %s. Returning raw text fallback.", exc)
        return cipher_text


# ── 2. Daily Gemini Budget Guard ──────────────────────────────────────

class GeminiBudgetGuard:
    """Thread-safe tracker for daily Gemini API calls."""

    def __init__(self, daily_limit: int = 50):
        self.daily_limit = daily_limit
        self._lock = threading.Lock()
        self._current_date = datetime.date.today()
        self._call_count = 0

    def _reset_if_new_day(self):
        today = datetime.date.today()
        if today != self._current_date:
            self._current_date = today
            self._call_count = 0
            logger.info("Reset Gemini call counter for new day: %s", today)

    def can_call(self) -> bool:
        """Check if Gemini budget is remaining today."""
        with self._lock:
            self._reset_if_new_day()
            return self._call_count < self.daily_limit

    def record_call(self) -> int:
        """Record an executed Gemini API call and return new count."""
        with self._lock:
            self._reset_if_new_day()
            self._call_count += 1
            remaining = max(0, self.daily_limit - self._call_count)
            logger.info(
                "Gemini API call recorded (%d/%d used, %d remaining today)",
                self._call_count, self.daily_limit, remaining
            )
            return self._call_count

    def get_status(self) -> dict:
        """Get current budget status."""
        with self._lock:
            self._reset_if_new_day()
            return {
                "date": str(self._current_date),
                "used": self._call_count,
                "limit": self.daily_limit,
                "remaining": max(0, self.daily_limit - self._call_count),
                "exceeded": self._call_count >= self.daily_limit,
            }


_BUDGET_GUARD = GeminiBudgetGuard(
    daily_limit=int(os.getenv("GEMINI_DAILY_LIMIT", "50"))
)


def get_budget_guard() -> GeminiBudgetGuard:
    return _BUDGET_GUARD


# ── 3. Upload & Zip-Bomb Security ─────────────────────────────────────

def check_docx_security(file_bytes: bytes, max_uncompressed_bytes: int = 20 * 1024 * 1024) -> None:
    """Inspect DOCX zip archive to prevent zip bombs, directory traversal, or excessive files.

    Raises:
        ValueError: If file is malformed or threatens decompression limits.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as zf:
            total_uncompressed = 0
            file_count = len(zf.infolist())

            if file_count > 500:
                raise ValueError(f"DOCX archive contains excessive entries ({file_count} > 500)")

            for info in zf.infolist():
                # Directory traversal check
                if ".." in info.filename or info.filename.startswith("/"):
                    raise ValueError("Suspicious path detected in DOCX archive")

                total_uncompressed += info.file_size
                if total_uncompressed > max_uncompressed_bytes:
                    raise ValueError(
                        f"DOCX uncompressed size exceeds safe limit "
                        f"({total_uncompressed / (1024 * 1024):.1f} MB > {max_uncompressed_bytes / (1024 * 1024)} MB)"
                    )
    except zipfile.BadZipFile as exc:
        raise ValueError(f"Invalid DOCX zip archive: {exc}") from exc


# ── 4. Rate Limiting ──────────────────────────────────────────────────

class RateLimiter:
    """Simple in-memory sliding window rate limiter per client IP."""

    def __init__(self, requests_per_minute: int = 15):
        self.rate = requests_per_minute
        self._history = collections.defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, client_id: str) -> bool:
        now = time.time()
        window_start = now - 60.0

        with self._lock:
            # Clean old records
            timestamps = [t for t in self._history[client_id] if t > window_start]
            if len(timestamps) >= self.rate:
                self._history[client_id] = timestamps
                return False

            timestamps.append(now)
            self._history[client_id] = timestamps
            return True


_GLOBAL_RATE_LIMITER = RateLimiter(requests_per_minute=20)


def get_rate_limiter() -> RateLimiter:
    return _GLOBAL_RATE_LIMITER


# ── 5. Password Authentication Gate ───────────────────────────────────

_LOCKOUT_ATTEMPTS = 5
_LOCKOUT_DURATION_SECONDS = 900  # 15 minutes
_FAILED_ATTEMPTS: dict[str, list[float]] = collections.defaultdict(list)
_AUTH_LOCK = threading.Lock()


def check_password_auth(provided_password: str, correct_password: str, client_ip: str = "default") -> tuple[bool, str]:
    """Verify password with constant-time comparison and brute-force lockout.

    Returns:
        (is_authenticated, message)
    """
    if not correct_password:
        return True, "Authentication disabled (no password configured)."

    now = time.time()
    with _AUTH_LOCK:
        # Purge attempts older than lockout duration
        recent_fails = [t for t in _FAILED_ATTEMPTS[client_ip] if now - t < _LOCKOUT_DURATION_SECONDS]
        _FAILED_ATTEMPTS[client_ip] = recent_fails

        if len(recent_fails) >= _LOCKOUT_ATTEMPTS:
            wait_min = int((_LOCKOUT_DURATION_SECONDS - (now - recent_fails[0])) / 60) + 1
            return False, f"Too many failed login attempts. Temporarily locked out for {wait_min} more minute(s)."

        # Constant-time comparison
        is_correct = hmac.compare_digest(
            provided_password.strip().encode("utf-8"),
            correct_password.strip().encode("utf-8"),
        )

        if is_correct:
            _FAILED_ATTEMPTS.pop(client_ip, None)
            return True, "Authenticated successfully."
        else:
            _FAILED_ATTEMPTS[client_ip].append(now)
            attempts_left = _LOCKOUT_ATTEMPTS - len(_FAILED_ATTEMPTS[client_ip])
            return False, f"Incorrect access password. {attempts_left} attempt(s) remaining before temporary lockout."
