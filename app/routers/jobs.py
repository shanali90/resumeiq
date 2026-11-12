"""Jobs router — upload, extract requirements, and retrieve job descriptions."""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import JobModel
from app.schemas import JobAnalysisResponse, JobDescription
from app.services.jd_analyzer import analyze_job_description

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.post(
    "",
    response_model=JobAnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create and analyze a job description",
)
async def create_job_endpoint(
    text: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    """Analyze and store a job description.

    Accepts plain text via form data OR a text/markdown file upload.
    Extracts seniority, required/preferred skills, education, experience, and responsibilities.
    """
    if not text and not file:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either job description text or a file must be provided.",
        )

    if file:
        file_bytes = await file.read()
        try:
            raw_text = file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            raw_text = file_bytes.decode("latin-1", errors="replace")
    else:
        raw_text = text or ""

    if not raw_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Job description text cannot be empty.",
        )

    try:
        jd_structure = analyze_job_description(raw_text)

        job_record = JobModel(
            title=jd_structure.title,
            raw_text=raw_text,
            jd_json=jd_structure.model_dump_json(),
        )
        db.add(job_record)
        db.commit()
        db.refresh(job_record)

        return JobAnalysisResponse(
            id=job_record.id,
            job_description=jd_structure,
        )
    except Exception as exc:
        logger.error("Job analysis failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to analyze job description: {str(exc)}",
        )


@router.get(
    "/{job_id}",
    response_model=JobAnalysisResponse,
    summary="Retrieve an analyzed job description",
)
def get_job_endpoint(
    job_id: int,
    db: Session = Depends(get_db),
):
    """Retrieve structured job requirements and details by ID."""
    job = db.query(JobModel).filter(JobModel.id == job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job description not found")

    jd_dict = json.loads(job.jd_json)
    return JobAnalysisResponse(
        id=job.id,
        job_description=JobDescription(**jd_dict),
    )
