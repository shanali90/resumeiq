"""Resume file parser — PDF and DOCX to clean text with security controls.

Handles:
- In-memory parsing only (zero temporary files written to disk)
- Multi-column layouts
- Magic bytes check (%PDF, PK)
- Max file size (5MB)
- PDF page cap (max 10 pages)
- Encrypted/password-protected PDF rejection
- DOCX zip-bomb / archive security checks
- Scanned/image-only PDF detection (low text yield error)
"""

from __future__ import annotations

import gc
import io
import logging
import re
from pathlib import Path
from typing import BinaryIO

from app.config import get_settings
from app.security import check_docx_security

logger = logging.getLogger(__name__)


class ParserError(Exception):
    """Raised when a file cannot be parsed."""


class FileValidationError(ParserError):
    """Raised for invalid file type, size, or content."""


class ScannedPDFError(ParserError):
    """Raised when a PDF appears to be scanned/image-only."""


def validate_file(
    filename: str,
    file_bytes: bytes,
    content_type: str | None = None,
) -> None:
    """Validate file extension, magic bytes, size, and archive security.

    Args:
        filename: Original filename.
        file_bytes: Raw file bytes.
        content_type: MIME type if available.

    Raises:
        FileValidationError: If validation fails.
    """
    settings = get_settings()

    # Check extension
    ext = Path(filename).suffix.lower()
    if ext not in settings.allowed_extensions:
        raise FileValidationError(
            f"Unsupported file type '{ext}'. Allowed: {', '.join(settings.allowed_extensions)}"
        )

    # Check size
    if len(file_bytes) > settings.max_file_size_bytes:
        raise FileValidationError(
            f"File exceeds maximum size of {settings.max_file_size_mb} MB "
            f"({len(file_bytes) / (1024 * 1024):.1f} MB)"
        )

    # Check not empty
    if len(file_bytes) == 0:
        raise FileValidationError("File is empty")

    # Validate file signature (magic bytes)
    if ext == ".pdf":
        if not file_bytes[:5].startswith(b"%PDF"):
            raise FileValidationError("File does not appear to be a valid PDF (invalid magic bytes)")
        _check_pdf_security(file_bytes, settings.max_pdf_pages)
    elif ext == ".docx":
        if not file_bytes[:4].startswith(b"PK"):
            raise FileValidationError("File does not appear to be a valid DOCX (invalid magic bytes)")
        try:
            check_docx_security(file_bytes, settings.max_docx_uncompressed_bytes)
        except ValueError as exc:
            raise FileValidationError(f"DOCX security validation failed: {exc}") from exc


def _check_pdf_security(file_bytes: bytes, max_pages: int) -> None:
    """Check for PDF encryption and page count limits."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))

        # Check encryption
        if getattr(reader, "is_encrypted", False):
            raise FileValidationError("Encrypted or password-protected PDFs are not supported.")

        # Check page count
        page_count = len(reader.pages)
        if page_count > max_pages:
            raise FileValidationError(
                f"PDF exceeds maximum page limit of {max_pages} pages ({page_count} pages detected)."
            )
    except FileValidationError:
        raise
    except Exception as exc:
        logger.warning("pypdf security pre-check encountered non-fatal issue: %s", exc)


def _extract_text_pdfplumber(file_bytes: bytes) -> str:
    """Extract text from PDF using pdfplumber in-memory (primary)."""
    try:
        import pdfplumber

        text_parts: list[str] = []
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                try:
                    page_text = page.extract_text(x_tolerance=2, y_tolerance=2)
                    if page_text:
                        text_parts.append(page_text)
                except Exception as exc:
                    logger.warning("pdfplumber failed on page %d: %s", page_num, exc)

        return "\n\n".join(text_parts)
    except Exception as exc:
        logger.warning("pdfplumber extraction failed: %s", exc)
        raise ParserError(f"pdfplumber extraction failed: {exc}") from exc


def _extract_text_pypdf(file_bytes: bytes) -> str:
    """Extract text from PDF using pypdf in-memory (fallback)."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(file_bytes))
        text_parts: list[str] = []

        for page_num, page in enumerate(reader.pages, 1):
            try:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
            except Exception as exc:
                logger.warning("pypdf failed on page %d: %s", page_num, exc)

        return "\n\n".join(text_parts)
    except Exception as exc:
        logger.warning("pypdf extraction failed: %s", exc)
        raise ParserError(f"pypdf extraction failed: {exc}") from exc


def _extract_text_docx(file_bytes: bytes) -> str:
    """Extract text from DOCX in-memory with paragraph limits."""
    settings = get_settings()
    try:
        from docx import Document

        doc = Document(io.BytesIO(file_bytes))
        text_parts: list[str] = []

        para_count = 0
        for para in doc.paragraphs:
            para_count += 1
            if para_count > settings.max_docx_paragraphs:
                logger.warning("DOCX exceeds maximum paragraph limit (%d). Truncating.", settings.max_docx_paragraphs)
                break
            text = para.text.strip()
            if text:
                text_parts.append(text)

        # Extract from tables
        for table in doc.tables:
            for row in table.rows:
                row_texts = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_texts:
                    text_parts.append(" | ".join(row_texts))

        return "\n".join(text_parts)
    except Exception as exc:
        raise ParserError(f"DOCX extraction failed: {exc}") from exc


def _clean_text(text: str) -> str:
    """Clean extracted text: normalize whitespace, bullets, hyphenation."""
    if not text:
        return ""

    # Fix hyphenation at line breaks
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)

    # Normalize bullet characters to "- "
    text = re.sub(
        r"^[\u2022\u2023\u25E6\u2043\u2219\u25AA\u25CF\u25CB\u2013\u2014•●○◦▪►▸‣]\s*",
        "- ",
        text,
        flags=re.MULTILINE,
    )

    # Normalize multiple spaces to single space
    text = re.sub(r"[ \t]+", " ", text)

    # Normalize multiple newlines to max 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Strip leading/trailing whitespace from each line
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines).strip()

    return text


def parse_file(
    filename: str,
    file_bytes: bytes,
    content_type: str | None = None,
) -> str:
    """Parse resume file in memory and return clean text.

    Args:
        filename: Original filename.
        file_bytes: Raw file bytes.
        content_type: MIME type if available.

    Returns:
        Cleaned extracted text.

    Raises:
        FileValidationError: If file is invalid or insecure.
        ScannedPDFError: If PDF is scanned/image-only.
        ParserError: If extraction fails.
    """
    settings = get_settings()

    # Validate file & security constraints
    validate_file(filename, file_bytes, content_type)

    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        text = _extract_pdf(file_bytes)
    elif ext == ".docx":
        text = _extract_text_docx(file_bytes)
    else:
        raise FileValidationError(f"Unsupported extension: {ext}")

    # Clean text
    text = _clean_text(text)

    # Free parsing buffers immediately to stay well under memory limits
    gc.collect()

    # Check for scanned PDF
    if ext == ".pdf" and len(text) < settings.scanned_pdf_min_chars:
        raise ScannedPDFError(
            "Scanned PDF detected: text not extractable. "
            "Please upload a text-based PDF or DOCX file."
        )

    logger.info("Parsed '%s': %d characters extracted in-memory", filename, len(text))
    return text


def _extract_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF in memory, trying pdfplumber first, then pypdf."""
    try:
        text = _extract_text_pdfplumber(file_bytes)
        if text.strip():
            return text
        logger.info("pdfplumber returned empty text, trying pypdf fallback")
    except ParserError:
        logger.info("pdfplumber failed, trying pypdf fallback")

    try:
        return _extract_text_pypdf(file_bytes)
    except ParserError as exc:
        raise ParserError(
            "Failed to extract text from PDF with both pdfplumber and pypdf"
        ) from exc
