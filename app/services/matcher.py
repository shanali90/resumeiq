"""Core matching engine — deterministic, explainable resume vs JD scoring.

Computes transparent weighted compatibility score (0-100):
- Required skills coverage: 40%
- Semantic similarity: 20% (local sentence-transformers or TF-IDF fallback)
- Preferred skills coverage: 10%
- Experience fit: 20%
- Education fit: 10%

Generates strengths, weaknesses, recommendations, and verdict band.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import numpy as np

from app.config import get_settings
from app.schemas import (
    ComponentScore,
    JobDescription,
    MatchResult,
    NormalizedSkill,
    ResumeProfile,
    Verdict,
)

logger = logging.getLogger(__name__)

# Cached embedding model singleton
_EMBEDDING_MODEL = None


def get_embedding_model() -> Any:
    """Load and cache the sentence-transformers model once at startup."""
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
            _EMBEDDING_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("Successfully loaded sentence-transformers model 'all-MiniLM-L6-v2'")
        except Exception as exc:
            logger.warning("sentence-transformers not available: %s. Using TF-IDF fallback.", exc)
            return None
    return _EMBEDDING_MODEL


def _compute_semantic_similarity(resume_text: str, jd_text: str) -> float:
    """Compute semantic similarity between resume and JD (0-100).

    Uses sentence-transformers if available; falls back to TF-IDF cosine similarity.
    """
    if not resume_text.strip() or not jd_text.strip():
        return 0.0

    model = get_embedding_model()
    if model is not None:
        try:
            embeddings = model.encode([resume_text, jd_text])
            v1, v2 = embeddings[0], embeddings[1]
            norm1 = np.linalg.norm(v1)
            norm2 = np.linalg.norm(v2)
            if norm1 > 0 and norm2 > 0:
                cosine = float(np.dot(v1, v2) / (norm1 * norm2))
                # Scale from typical [-0.2, 1.0] to [0, 100]
                scaled = max(0.0, min(100.0, cosine * 100.0))
                return round(scaled, 1)
        except Exception as exc:
            logger.warning("Neural embedding failed: %s, falling back to TF-IDF", exc)

    # TF-IDF fallback
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    try:
        vec = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", max_features=1000)
        matrix = vec.fit_transform([resume_text, jd_text])
        sim = float(cosine_similarity(matrix[0:1], matrix[1:2])[0][0])
        # Scale TF-IDF cosine (typical related technical documents score 0.25 - 0.50)
        scaled = min(100.0, sim * 180.0)
        return round(max(0.0, scaled), 1)
    except Exception as exc:
        logger.warning("TF-IDF similarity failed: %s", exc)
        return 50.0


# Semantic skill cluster mapping for partial credit
SKILL_SEMANTIC_PAIRS = {
    "deep learning": ["pytorch", "tensorflow", "keras", "neural networks"],
    "deep learning architectures": ["pytorch", "tensorflow", "transformer", "neural networks"],
    "machine learning": ["scikit-learn", "xgboost", "lightgbm", "ml"],
    "nlp": ["transformers", "hugging face", "spacy", "nltk", "langchain", "llm"],
    "computer vision": ["opencv", "yolo", "torchvision", "image processing"],
    "cloud": ["aws", "azure", "google cloud platform", "gcp"],
    "containerization": ["docker", "podman", "kubernetes"],
    "relational database": ["postgresql", "mysql", "sql server", "sqlite", "oracle database"],
    "nosql": ["mongodb", "redis", "dynamodb", "cassandra"],
}


def _match_skill_list(
    jd_skills: list[str],
    candidate_skills: list[NormalizedSkill],
    resume_text: str = "",
) -> tuple[float, list[str], list[str]]:
    """Match JD skill list against candidate skills with partial semantic credit.

    Returns:
        (coverage_score_0_to_100, matched_skills, missing_skills)
    """
    if not jd_skills:
        return 100.0, [], []

    matched: list[str] = []
    missing: list[str] = []

    # Map candidate skill names (lowercase)
    cand_skill_map: dict[str, str] = {s.normalized.lower(): s.normalized for s in candidate_skills}
    resume_lower = resume_text.lower()

    total_credit = 0.0

    for jd_skill in jd_skills:
        jd_lower = jd_skill.lower().strip()

        # 1. Exact canonical or raw match
        if jd_lower in cand_skill_map:
            matched.append(cand_skill_map[jd_lower])
            total_credit += 1.0
            continue

        # 2. Check if skill name is in raw resume text
        pattern = r"\b" + re.escape(jd_lower) + r"\b"
        if re.search(pattern, resume_lower):
            matched.append(jd_skill)
            total_credit += 1.0
            continue

        # 3. Semantic near-match (partial credit: 0.7)
        partial_match_found = False
        for broad_term, specific_skills in SKILL_SEMANTIC_PAIRS.items():
            if broad_term in jd_lower:
                # Candidate has one of the specific technologies
                matching_specifics = [s for s in specific_skills if s in cand_skill_map or s in resume_lower]
                if matching_specifics:
                    matched_name = f"{jd_skill} (via {cand_skill_map.get(matching_specifics[0], matching_specifics[0])})"
                    matched.append(matched_name)
                    total_credit += 0.70
                    partial_match_found = True
                    break

        if not partial_match_found:
            missing.append(jd_skill)

    coverage = round((total_credit / len(jd_skills)) * 100.0, 1)
    coverage = max(0.0, min(100.0, coverage))
    return coverage, matched, missing


DEGREE_RANKS = {
    "phd": 5, "ph.d": 5, "doctorate": 5,
    "ms": 4, "m.s.": 4, "master": 4, "mba": 4, "m.tech": 4,
    "bs": 3, "b.s.": 3, "bachelor": 3, "b.tech": 3, "b.e.": 3,
    "associate": 2, "diploma": 2,
    "some college": 1, "high school": 1,
}


def _score_education_fit(profile: ResumeProfile, jd: JobDescription) -> tuple[float, str]:
    """Score education fit (0-100)."""
    if not jd.education_requirement:
        return 100.0, "No specific education requirement specified in job description."

    jd_edu_lower = jd.education_requirement.lower()

    # Determine required level — if "BS or MS" or "MS or PhD", take the minimum acceptable
    found_ranks = [rank for deg, rank in DEGREE_RANKS.items() if re.search(r"\b" + re.escape(deg) + r"\b", jd_edu_lower)]
    req_rank = min(found_ranks) if found_ranks else 3

    # Determine candidate's highest level
    cand_rank = 0
    cand_highest_degree = "None"
    for edu in profile.education:
        deg_str = (edu.degree or "").lower()
        for deg, rank in DEGREE_RANKS.items():
            if re.search(r"\b" + re.escape(deg) + r"\b", deg_str):
                if rank > cand_rank:
                    cand_rank = rank
                    cand_highest_degree = edu.degree or deg

    if cand_rank == 0 and profile.education:
        cand_rank = 3  # Assume standard college degree if education listed
        cand_highest_degree = profile.education[0].degree or "Degree"

    if cand_rank >= req_rank:
        return 100.0, f"Candidate degree ({cand_highest_degree}) meets or exceeds requirement ({jd.education_requirement})."
    elif cand_rank == req_rank - 1:
        return 75.0, f"Candidate degree ({cand_highest_degree}) is close to requirement ({jd.education_requirement})."
    else:
        return 40.0, f"Candidate degree ({cand_highest_degree}) is below requirement ({jd.education_requirement})."


def _score_experience_fit(profile: ResumeProfile, jd: JobDescription) -> tuple[float, str]:
    """Score experience duration and seniority fit (0-100)."""
    # Calculate candidate years of experience
    cand_months = profile.total_experience_months or 0
    if cand_months == 0:
        for exp in profile.experience:
            if exp.duration_months and not exp.is_internship:
                cand_months += exp.duration_months
        if cand_months == 0 and profile.experience:
            cand_months = len(profile.experience) * 18  # Estimate 1.5 yrs per job

    cand_years = round(cand_months / 12.0, 1)
    req_years = jd.min_experience_years or 0

    if req_years == 0:
        return 100.0, f"Candidate has {cand_years} years of experience (no minimum required)."

    # Duration score
    if cand_years >= req_years:
        dur_score = 100.0
    elif cand_years >= req_years - 1:
        dur_score = 80.0
    elif cand_years >= req_years - 2:
        dur_score = 60.0
    else:
        dur_score = max(20.0, (cand_years / req_years) * 60.0)

    # Title relevance check
    title_words = set(re.findall(r"\w+", (jd.title or "").lower()))
    title_matches = 0
    for exp in profile.experience:
        exp_title = (exp.title or "").lower()
        if any(w in exp_title for w in title_words if len(w) > 3):
            title_matches += 1

    title_factor = 1.0 if title_matches > 0 or not jd.title else 0.85
    final_score = round(min(100.0, dur_score * title_factor), 1)

    details = (
        f"{cand_years} years experience vs {req_years} required "
        f"({title_matches} relevant titles held)"
    )
    return final_score, details


def match_resume_to_job(
    profile: ResumeProfile,
    normalized_skills: list[NormalizedSkill],
    jd: JobDescription,
    resume_text: str = "",
    jd_text: str = "",
) -> MatchResult:
    """Compute transparent compatibility score and report between resume and JD.

    Args:
        profile: Candidate profile.
        normalized_skills: Extracted skills.
        jd: Structured job description.
        resume_text: Clean resume text.
        jd_text: Full job description text.

    Returns:
        Structured MatchResult with explainable scores and evidence.
    """
    settings = get_settings()

    # 1. Required skills (40%)
    req_score, matched_req, missing_req = _match_skill_list(
        jd.required_skills, normalized_skills, resume_text
    )

    # 2. Semantic similarity (20%)
    sem_score = _compute_semantic_similarity(resume_text, jd_text)

    # 3. Preferred skills (10%)
    pref_score, matched_pref, missing_pref = _match_skill_list(
        jd.preferred_skills, normalized_skills, resume_text
    )

    # 4. Experience fit (20%)
    exp_score, exp_details = _score_experience_fit(profile, jd)

    # 5. Education fit (10%)
    edu_score, edu_details = _score_education_fit(profile, jd)

    # Extra relevant skills (candidate has skills from the taxonomy that are relevant to the domain)
    all_jd_skills = {s.lower() for s in jd.required_skills + jd.preferred_skills}
    extra_skills = [
        s.normalized for s in normalized_skills
        if s.normalized.lower() not in all_jd_skills
    ][:8]

    # Weighted sum
    w_req = settings.weight_required_skills
    w_sem = settings.weight_semantic_similarity
    w_pref = settings.weight_preferred_skills
    w_exp = settings.weight_experience_fit
    w_edu = settings.weight_education_fit

    overall = (
        req_score * w_req
        + sem_score * w_sem
        + pref_score * w_pref
        + exp_score * w_exp
        + edu_score * w_edu
    )
    overall = round(max(0.0, min(100.0, overall)), 1)

    # Verdict band
    if overall >= settings.verdict_strong:
        verdict = Verdict.STRONG
    elif overall >= settings.verdict_good:
        verdict = Verdict.GOOD
    elif overall >= settings.verdict_partial:
        verdict = Verdict.PARTIAL
    else:
        verdict = Verdict.WEAK

    # Component scores
    components = [
        ComponentScore(
            name="Required Skills Coverage",
            score=req_score,
            weight=w_req,
            weighted_score=round(req_score * w_req, 1),
            details=f"Matched {len(matched_req)}/{len(jd.required_skills)} required skills ({req_score}%)",
        ),
        ComponentScore(
            name="Semantic Similarity",
            score=sem_score,
            weight=w_sem,
            weighted_score=round(sem_score * w_sem, 1),
            details=f"Cosine embedding similarity of resume and job description: {sem_score}%",
        ),
        ComponentScore(
            name="Preferred Skills Coverage",
            score=pref_score,
            weight=w_pref,
            weighted_score=round(pref_score * w_pref, 1),
            details=f"Matched {len(matched_pref)}/{len(jd.preferred_skills)} preferred skills ({pref_score}%)",
        ),
        ComponentScore(
            name="Experience Fit",
            score=exp_score,
            weight=w_exp,
            weighted_score=round(exp_score * w_exp, 1),
            details=exp_details,
        ),
        ComponentScore(
            name="Education Fit",
            score=edu_score,
            weight=w_edu,
            weighted_score=round(edu_score * w_edu, 1),
            details=edu_details,
        ),
    ]

    # Strengths, weaknesses, and evidence-tied recommendations
    strengths: list[str] = []
    weaknesses: list[str] = []
    recommendations: list[str] = []

    if req_score >= 75.0:
        strengths.append(
            f"Strong required skills alignment ({len(matched_req)}/{len(jd.required_skills)} matched: {', '.join(matched_req[:5])})."
        )
    elif req_score < 50.0:
        weaknesses.append(
            f"Low required skills coverage ({len(matched_req)}/{len(jd.required_skills)} matched). Missing core requirements: {', '.join(missing_req[:4])}."
        )

    if exp_score >= 80.0:
        strengths.append(f"Solid experience track record: {exp_details}.")
    elif exp_score < 60.0:
        weaknesses.append(f"Experience gap: {exp_details}.")

    if matched_pref:
        strengths.append(f"Possesses desirable preferred qualifications: {', '.join(matched_pref[:4])}.")

    if missing_req:
        recommendations.append(
            f"Address missing required skills: Prioritize building or highlighting expertise in {', '.join(missing_req[:3])}."
        )

    if missing_pref:
        recommendations.append(
            f"Enhance competitive edge by adding bonus skills: {', '.join(missing_pref[:3])}."
        )

    if sem_score < 55.0:
        recommendations.append(
            "Tailor resume terminology to reflect the job description's domain vocabulary and industry phrasing."
        )

    return MatchResult(
        overall_score=overall,
        verdict=verdict,
        component_scores=components,
        matched_skills=matched_req + matched_pref,
        missing_required_skills=missing_req,
        missing_preferred_skills=missing_pref,
        extra_relevant_skills=extra_skills,
        strengths=strengths,
        weaknesses=weaknesses,
        recommendations=recommendations,
    )
