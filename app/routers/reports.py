"""Reports router — generate and download professional PDF and JSON match reports."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import JobModel, MatchModel, ResumeModel
from app.schemas import KeywordAnalysis, MatchResult
from app.services.keywords import analyze_keywords
from app.services.report import generate_candidate_pdf

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get(
    "",
    summary="List past match reports",
)
def list_reports_endpoint(
    db: Session = Depends(get_db),
):
    """List all stored match evaluations with candidate name, job title, and score."""
    matches = db.query(MatchModel).order_by(MatchModel.created_at.desc()).limit(50).all()
    results = []
    for m in matches:
        resume = db.query(ResumeModel).filter(ResumeModel.id == m.resume_id).first()
        job = db.query(JobModel).filter(JobModel.id == m.job_id).first()
        results.append({
            "id": m.id,
            "resume_id": m.resume_id,
            "job_id": m.job_id,
            "candidate_name": resume.candidate_name if resume else "Candidate",
            "job_title": job.title if job else "Job",
            "overall_score": m.overall_score,
            "verdict": m.verdict,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        })
    return results


@router.get(
    "/{match_id}.json",
    summary="Download match report as structured JSON",
)
def get_report_json_endpoint(
    match_id: int,
    db: Session = Depends(get_db),
):
    """Retrieve full match report in JSON format."""
    match = db.query(MatchModel).filter(MatchModel.id == match_id).first()
    if not match:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

    resume = db.query(ResumeModel).filter(ResumeModel.id == match.resume_id).first()
    job = db.query(JobModel).filter(JobModel.id == match.job_id).first()

    return {
        "match_id": match.id,
        "candidate_name": resume.candidate_name if resume else "Candidate",
        "job_title": job.title if job else "Job",
        "overall_score": match.overall_score,
        "verdict": match.verdict,
        "evaluation": json.loads(match.match_json),
    }


@router.get(
    "/{match_id}.pdf",
    summary="Download match report as formatted PDF",
)
def get_report_pdf_endpoint(
    match_id: int,
    db: Session = Depends(get_db),
):
    """Download professional PDF evaluation report for a candidate match."""
    match = db.query(MatchModel).filter(MatchModel.id == match_id).first()
    if not match:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found")

    resume = db.query(ResumeModel).filter(ResumeModel.id == match.resume_id).first()
    job = db.query(JobModel).filter(JobModel.id == match.job_id).first()

    candidate_name = (resume.candidate_name if resume else None) or "Candidate"
    job_title = (job.title if job else None) or "Target Role"

    match_result = MatchResult(**json.loads(match.match_json))

    # Compute keyword analysis for report
    kw_analysis = None
    if resume and job:
        try:
            kw_analysis = analyze_keywords(resume.raw_text, job.raw_text)
        except Exception:
            kw_analysis = None

    try:
        pdf_bytes = generate_candidate_pdf(
            candidate_name=candidate_name,
            job_title=job_title,
            match_result=match_result,
            keyword_analysis=kw_analysis,
        )

        filename = f"report_{match_id}_{candidate_name.replace(' ', '_')}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as exc:
        logger.error("PDF generation failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate PDF: {str(exc)}",
        )
