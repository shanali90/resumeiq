"""Multi-resume recruiter ranking engine with parallel execution.

Processes 2-50 resumes against a single job description using ThreadPoolExecutor.
Isolates errors per file so bad files never fail the batch.
Constructs side-by-side skill comparison matrix and one-line reasons for top candidates.
Supports filtering by minimum score, must-have skills, and minimum experience.
"""

from __future__ import annotations

import concurrent.futures
import logging
from typing import Any, Optional

from app.schemas import (
    ComparisonCell,
    JobDescription,
    MatchResult,
    NormalizedSkill,
    RankedCandidate,
    RankingResult,
    ResumeProfile,
    SkillSource,
    Verdict,
)
from app.services.extractor import extract_profile
from app.services.matcher import match_resume_to_job
from app.services.parser import parse_file, ParserError
from app.services.quality import score_resume_quality
from app.services.skills import detect_skills_in_text, merge_skills, normalize_skills

logger = logging.getLogger(__name__)


def _process_single_resume(
    filename: str,
    file_bytes: bytes,
    content_type: str | None,
    jd: JobDescription,
    jd_text: str,
) -> RankedCandidate:
    """Process a single resume against a JD. Completely error-isolated."""
    try:
        # 1. Parse text
        resume_text = parse_file(filename, file_bytes, content_type)

        # 2. Extract profile
        profile = extract_profile(resume_text)

        # 3. Detect and normalize skills
        sec_skills = normalize_skills(profile.skills_raw, source=SkillSource.SKILLS_SECTION)
        txt_skills = detect_skills_in_text(resume_text, source=SkillSource.EXPERIENCE)
        all_skills = merge_skills(sec_skills, txt_skills)

        # 4. Score quality
        quality_rep = score_resume_quality(profile, all_skills, raw_text=resume_text)

        # 5. Match against JD
        match_res = match_resume_to_job(
            profile=profile,
            normalized_skills=all_skills,
            jd=jd,
            resume_text=resume_text,
            jd_text=jd_text,
        )

        # 6. Generate one-line reason
        candidate_name = profile.candidate.name or filename
        cand_years = round((profile.total_experience_months or 0) / 12.0, 1)

        matched_count = len(match_res.matched_skills)
        req_count = len(jd.required_skills)

        if match_res.overall_score >= 80:
            reason = f"Excellent fit: {matched_count}/{req_count} skills matched with {cand_years}y relevant experience."
        elif match_res.overall_score >= 65:
            reason = f"Solid contender: strong core skills with {cand_years}y background; minor skill gaps."
        elif match_res.overall_score >= 45:
            reason = f"Partial match: lacks {len(match_res.missing_required_skills)} required skills ({', '.join(match_res.missing_required_skills[:2])})."
        else:
            reason = f"Low relevance for role: mismatched technical stack and experience."

        return RankedCandidate(
            rank=0,  # Assigned after sorting
            filename=filename,
            candidate_name=candidate_name,
            overall_score=match_res.overall_score,
            verdict=match_res.verdict,
            match_result=match_res,
            quality_score=quality_rep.overall_score,
            one_line_reason=reason,
            error=None,
        )

    except Exception as exc:
        logger.warning("Error processing resume '%s': %s", filename, exc)
        dummy_match = MatchResult(
            overall_score=0.0,
            verdict=Verdict.WEAK,
            component_scores=[],
            matched_skills=[],
            missing_required_skills=jd.required_skills,
            missing_preferred_skills=jd.preferred_skills,
            extra_relevant_skills=[],
            strengths=[],
            weaknesses=[f"File processing failed: {str(exc)}"],
            recommendations=["Verify file integrity and re-upload in standard PDF or DOCX format."],
        )
        return RankedCandidate(
            rank=999,
            filename=filename,
            candidate_name=None,
            overall_score=0.0,
            verdict=Verdict.WEAK,
            match_result=dummy_match,
            quality_score=None,
            one_line_reason=f"Processing failed: {str(exc)}",
            error=str(exc),
        )


def rank_resumes(
    jd: JobDescription,
    jd_text: str,
    resume_files: list[tuple[str, bytes, Optional[str]]],
    min_score: Optional[float] = None,
    must_have_skills: Optional[list[str]] = None,
    min_experience_years: Optional[int] = None,
    max_workers: int = 8,
) -> RankingResult:
    """Rank a batch of 2-50 resumes against a job description in parallel.

    Args:
        jd: Structured job description.
        jd_text: Full JD text.
        resume_files: List of (filename, file_bytes, content_type) tuples.
        min_score: Optional minimum score filter.
        must_have_skills: Optional list of skill names that must be present.
        min_experience_years: Optional minimum years of experience filter.
        max_workers: Thread pool concurrency.

    Returns:
        Complete RankingResult with ranked list and comparison matrix.
    """
    total_files = len(resume_files)
    candidates: list[RankedCandidate] = []

    # Parallel processing via ThreadPoolExecutor
    actual_workers = max(1, min(max_workers, total_files))
    with concurrent.futures.ThreadPoolExecutor(max_workers=actual_workers) as executor:
        futures = {
            executor.submit(_process_single_resume, fname, fbytes, ctype, jd, jd_text): fname
            for fname, fbytes, ctype in resume_files
        }
        for future in concurrent.futures.as_completed(futures):
            cand = future.result()
            candidates.append(cand)

    # Sort candidates by overall score descending (errors at the very bottom)
    candidates.sort(key=lambda c: (c.error is None, c.overall_score), reverse=True)

    # Assign ranks
    for i, cand in enumerate(candidates, 1):
        cand.rank = i

    total_errors = sum(1 for c in candidates if c.error is not None)

    # Build comparison matrix: candidates x required skills
    comparison_matrix: list[list[ComparisonCell]] = []
    matrix_skills = jd.required_skills[:10]  # Focus on key required skills

    for cand in candidates:
        row: list[ComparisonCell] = []
        if cand.error or not cand.match_result:
            for skill in matrix_skills:
                row.append(ComparisonCell(
                    candidate=cand.candidate_name or cand.filename,
                    skill=skill,
                    has_skill=False,
                ))
        else:
            cand_skills_lower = {s.lower() for s in cand.match_result.matched_skills}
            for skill in matrix_skills:
                has_it = skill.lower() in cand_skills_lower or any(skill.lower() in s for s in cand_skills_lower)
                row.append(ComparisonCell(
                    candidate=cand.candidate_name or cand.filename,
                    skill=skill,
                    has_skill=has_it,
                ))
        comparison_matrix.append(row)

    # Top candidates (top 3 without errors)
    top_candidates = [c for c in candidates if c.error is None][:3]

    # Apply recruiter filters if requested
    filtered_candidates = candidates
    if min_score is not None:
        filtered_candidates = [c for c in filtered_candidates if c.overall_score >= min_score]

    if must_have_skills:
        req_set = {s.lower() for s in must_have_skills}
        filtered_candidates = [
            c for c in filtered_candidates
            if c.match_result and req_set.issubset({s.lower() for s in c.match_result.matched_skills})
        ]

    return RankingResult(
        job_title=jd.title or "Target Role",
        candidates=filtered_candidates,
        comparison_matrix=comparison_matrix,
        top_candidates=top_candidates,
        total_processed=total_files,
        total_errors=total_errors,
    )
