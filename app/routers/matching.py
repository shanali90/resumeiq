"""Matching and ranking router — individual match analysis and batch recruiter ranking."""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import JobModel, MatchModel, ResumeModel
from app.schemas import (
    JobDescription,
    MatchRequest,
    MatchResult,
    NormalizedSkill,
    RankingResult,
    ResumeProfile,
)
from app.services.jd_analyzer import analyze_job_description
from app.services.matcher import match_resume_to_job
from app.services.ranker import rank_resumes

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Matching & Ranking"])


@router.post(
    "/match",
    response_model=MatchResult,
    summary="Match a single resume against a job description",
)
def match_endpoint(
    req: MatchRequest,
    db: Session = Depends(get_db),
):
    """Compute transparent compatibility score between a stored resume and a job description.

    Weights:
    - Required skills: 40%
    - Semantic similarity: 20%
    - Preferred skills: 10%
    - Experience fit: 20%
    - Education fit: 10%
    """
    resume = db.query(ResumeModel).filter(ResumeModel.id == req.resume_id).first()
    if not resume:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")

    job = db.query(JobModel).filter(JobModel.id == req.job_id).first()
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job description not found")

    profile = ResumeProfile(**json.loads(resume.profile_json))
    skills = [NormalizedSkill(**s) for s in json.loads(resume.skills_json)]
    jd = JobDescription(**json.loads(job.jd_json))

    match_result = match_resume_to_job(
        profile=profile,
        normalized_skills=skills,
        jd=jd,
        resume_text=resume.raw_text,
        jd_text=job.raw_text,
    )

    # Persist match
    match_record = MatchModel(
        resume_id=resume.id,
        job_id=job.id,
        overall_score=match_result.overall_score,
        verdict=match_result.verdict.value,
        match_json=match_result.model_dump_json(),
    )
    db.add(match_record)
    db.commit()
    db.refresh(match_record)

    return match_result


@router.post(
    "/rank",
    response_model=RankingResult,
    summary="Rank multiple resumes against a job description (batch)",
)
async def rank_endpoint(
    job_id: Optional[int] = Form(None),
    job_text: Optional[str] = Form(None),
    files: list[UploadFile] = File(...),
    min_score: Optional[float] = Form(None),
    must_have_skills: Optional[str] = Form(None),
    min_experience_years: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    """Batch rank 2-50 resumes against a job description in parallel.

    Uses ThreadPoolExecutor for error-isolated parallel processing.
    Generates side-by-side required skill comparison matrix and top candidate reasons.
    """
    if not files or len(files) < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least 1 resume file must be uploaded for ranking.",
        )

    # Resolve JD
    if job_id:
        job = db.query(JobModel).filter(JobModel.id == job_id).first()
        if not job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
        jd = JobDescription(**json.loads(job.jd_json))
        jd_raw = job.raw_text
    elif job_text and job_text.strip():
        jd = analyze_job_description(job_text)
        jd_raw = job_text
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either job_id or job_text must be provided.",
        )

    # Read all uploaded files
    resume_files: list[tuple[str, bytes, Optional[str]]] = []
    for f in files:
        content = await f.read()
        resume_files.append((f.filename or "resume.pdf", content, f.content_type))

    # Parse must-have skills if provided
    skills_filter = None
    if must_have_skills:
        skills_filter = [s.strip() for s in must_have_skills.split(",") if s.strip()]

    # Run ranking
    result = rank_resumes(
        jd=jd,
        jd_text=jd_raw,
        resume_files=resume_files,
        min_score=min_score,
        must_have_skills=skills_filter,
        min_experience_years=min_experience_years,
    )

    return result
