"""Resumes router — upload, analyze, retrieve, and delete resumes."""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ResumeModel
from app.schemas import (
    NormalizedSkill,
    QualityReport,
    ResumeAnalysisResponse,
    ResumeProfile,
    SkillSource,
)
from app.services.extractor import extract_profile
from app.services.parser import parse_file, ParserError, FileValidationError, ScannedPDFError
from app.services.quality import score_resume_quality
from app.services.skills import detect_skills_in_text, merge_skills, normalize_skills

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/resumes", tags=["Resumes"])


@router.post(
    "/analyze",
    response_model=ResumeAnalysisResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and analyze a resume",
)
async def analyze_resume_endpoint(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a resume file (PDF or DOCX, max 5 MB).

    Parses the file, extracts structured profile information,
    normalizes all skills, computes quality score and improvement suggestions,
    and stores the record in SQLite.
    """
    try:
        content = await file.read()
        filename = file.filename or "uploaded_resume.pdf"
        content_type = file.content_type

        # 1. Parse file
        clean_text = parse_file(filename, content, content_type)

        # 2. Extract profile
        profile = extract_profile(clean_text)

        # 3. Detect and normalize skills
        sec_skills = normalize_skills(profile.skills_raw, source=SkillSource.SKILLS_SECTION)
        txt_skills = detect_skills_in_text(clean_text, source=SkillSource.EXPERIENCE)
        all_skills = merge_skills(sec_skills, txt_skills)

        # 4. Score quality
        quality_report = score_resume_quality(profile, all_skills, raw_text=clean_text)

        # 5. Persist to DB
        resume_record = ResumeModel(
            filename=filename,
            candidate_name=profile.candidate.name,
            raw_text=clean_text,
            profile_json=profile.model_dump_json(),
            quality_json=quality_report.model_dump_json(),
            skills_json=json.dumps([s.model_dump() for s in all_skills]),
        )
        db.add(resume_record)
        db.commit()
        db.refresh(resume_record)

        return ResumeAnalysisResponse(
            id=resume_record.id,
            filename=filename,
            profile=profile,
            quality=quality_report,
            skills=all_skills,
        )

    except (FileValidationError, ScannedPDFError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except Exception as exc:
        logger.error("Resume analysis failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process resume: {str(exc)}",
        )


@router.get(
    "/{resume_id}",
    response_model=ResumeAnalysisResponse,
    summary="Retrieve an analyzed resume",
)
def get_resume_endpoint(
    resume_id: int,
    db: Session = Depends(get_db),
):
    """Retrieve structured analysis and quality breakdown of an analyzed resume."""
    resume = db.query(ResumeModel).filter(ResumeModel.id == resume_id).first()
    if not resume:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")

    profile_dict = json.loads(resume.profile_json)
    quality_dict = json.loads(resume.quality_json)
    skills_list = [NormalizedSkill(**s) for s in json.loads(resume.skills_json)]

    return ResumeAnalysisResponse(
        id=resume.id,
        filename=resume.filename,
        profile=ResumeProfile(**profile_dict),
        quality=QualityReport(**quality_dict),
        skills=skills_list,
    )


@router.delete(
    "/{resume_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a resume (privacy compliance)",
)
def delete_resume_endpoint(
    resume_id: int,
    db: Session = Depends(get_db),
):
    """Permanently delete a resume and all associated match results."""
    resume = db.query(ResumeModel).filter(ResumeModel.id == resume_id).first()
    if not resume:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")

    db.delete(resume)
    db.commit()
    return {"message": f"Resume {resume_id} and associated matches deleted successfully."}


@router.delete(
    "",
    status_code=status.HTTP_200_OK,
    summary="Purge all user data (privacy compliance)",
)
def purge_all_user_data(db: Session = Depends(get_db)):
    """Permanently delete all stored resumes, jobs, and matches."""
    res_count = db.query(ResumeModel).delete()
    db.commit()
    return {"message": f"All user data permanently deleted ({res_count} resume(s) purged)."}
