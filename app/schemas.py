"""Pydantic v2 schemas for ResumeIQ — all request/response models."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, EmailStr


# ── Enums ──────────────────────────────────────────────────────────────

class ExtractionMode(str, Enum):
    LLM = "llm"
    RULE_BASED = "rule_based"


class SkillCategory(str, Enum):
    TECHNICAL = "technical"
    SOFT = "soft"


class Severity(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Verdict(str, Enum):
    STRONG = "Strong"
    GOOD = "Good"
    PARTIAL = "Partial"
    WEAK = "Weak"


class SkillSource(str, Enum):
    SKILLS_SECTION = "skills_section"
    EXPERIENCE = "experience"
    PROJECT = "project"
    EDUCATION = "education"
    SUMMARY = "summary"


# ── Contact & Profile ─────────────────────────────────────────────────

class CandidateContact(BaseModel):
    """Candidate contact information."""
    model_config = {"extra": "forbid"}
    name: Optional[str] = Field(None, max_length=150)
    email: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    location: Optional[str] = Field(None, max_length=150)
    linkedin: Optional[str] = Field(None, max_length=300)
    github: Optional[str] = Field(None, max_length=300)
    portfolio: Optional[str] = Field(None, max_length=300)


# ── Education ──────────────────────────────────────────────────────────

class Education(BaseModel):
    """Single education entry."""
    degree: Optional[str] = None
    field: Optional[str] = None
    institution: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    grade: Optional[str] = None


# ── Experience ─────────────────────────────────────────────────────────

class Experience(BaseModel):
    """Single work experience entry."""
    title: Optional[str] = None
    company: Optional[str] = None
    start: Optional[str] = None
    end: Optional[str] = None
    duration_months: Optional[int] = None
    bullets: list[str] = Field(default_factory=list)
    is_internship: bool = False


# ── Projects ───────────────────────────────────────────────────────────

class Project(BaseModel):
    """Single project entry."""
    name: Optional[str] = None
    description: Optional[str] = None
    technologies: list[str] = Field(default_factory=list)


# ── Skills ─────────────────────────────────────────────────────────────

class NormalizedSkill(BaseModel):
    """A skill after normalization and categorization."""
    raw: str
    normalized: str
    category: SkillCategory
    sources: list[SkillSource] = Field(default_factory=list)


# ── Resume Profile ────────────────────────────────────────────────────

class ResumeProfile(BaseModel):
    """Complete extracted resume profile."""
    candidate: CandidateContact = Field(default_factory=CandidateContact)
    summary: Optional[str] = None
    education: list[Education] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    skills_raw: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    total_experience_months: Optional[int] = None
    extraction_mode: ExtractionMode = ExtractionMode.RULE_BASED


# ── Quality Scoring ───────────────────────────────────────────────────

class QualityComponent(BaseModel):
    """Single quality score component."""
    name: str
    score: float
    max_score: float
    details: str


class ImprovementSuggestion(BaseModel):
    """A suggestion for improving the resume."""
    category: str
    severity: Severity
    issue: str
    fix: str
    rewritten_example: Optional[str] = None


class QualityReport(BaseModel):
    """Complete quality assessment."""
    overall_score: float = Field(ge=0, le=100)
    components: list[QualityComponent] = Field(default_factory=list)
    improvement_suggestions: list[ImprovementSuggestion] = Field(default_factory=list)
    missing_skills_for_role: list[str] = Field(default_factory=list)
    inferred_role: Optional[str] = None


# ── Job Description ───────────────────────────────────────────────────

class JobDescription(BaseModel):
    """Structured job description."""
    title: Optional[str] = None
    seniority: Optional[str] = None
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    min_experience_years: Optional[int] = None
    education_requirement: Optional[str] = None
    responsibilities: list[str] = Field(default_factory=list)
    domain_keywords: list[str] = Field(default_factory=list)
    extraction_mode: ExtractionMode = ExtractionMode.RULE_BASED


# ── Matching ──────────────────────────────────────────────────────────

class ComponentScore(BaseModel):
    """Score for one matching component."""
    name: str
    score: float = Field(ge=0, le=100)
    weight: float
    weighted_score: float
    details: str


class MatchResult(BaseModel):
    """Complete match analysis between a resume and a job description."""
    overall_score: float = Field(ge=0, le=100)
    verdict: Verdict
    component_scores: list[ComponentScore] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    missing_required_skills: list[str] = Field(default_factory=list)
    missing_preferred_skills: list[str] = Field(default_factory=list)
    extra_relevant_skills: list[str] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


# ── Keywords ──────────────────────────────────────────────────────────

class KeywordGap(BaseModel):
    """A missing keyword with suggestion."""
    keyword: str
    importance: float = Field(ge=0, le=1)
    suggestion: str


class KeywordAnalysis(BaseModel):
    """Keyword optimization analysis."""
    ats_match_percentage: float = Field(ge=0, le=100)
    matched_keywords: list[str] = Field(default_factory=list)
    missing_keywords: list[KeywordGap] = Field(default_factory=list)


# ── Ranking ───────────────────────────────────────────────────────────

class RankedCandidate(BaseModel):
    """A candidate in the ranked list."""
    rank: int
    filename: str
    candidate_name: Optional[str] = None
    overall_score: float
    verdict: Verdict
    match_result: MatchResult
    quality_score: Optional[float] = None
    one_line_reason: Optional[str] = None
    error: Optional[str] = None


class ComparisonCell(BaseModel):
    """One cell in the comparison matrix."""
    candidate: str
    skill: str
    has_skill: bool


class RankingResult(BaseModel):
    """Complete ranking result for a batch."""
    job_title: Optional[str] = None
    candidates: list[RankedCandidate] = Field(default_factory=list)
    comparison_matrix: list[list[ComparisonCell]] = Field(default_factory=list)
    top_candidates: list[RankedCandidate] = Field(default_factory=list)
    total_processed: int = 0
    total_errors: int = 0


# ── API Request/Response Models ───────────────────────────────────────

class ResumeAnalysisResponse(BaseModel):
    """Response for resume analysis."""
    id: int
    filename: str
    profile: ResumeProfile
    quality: QualityReport
    skills: list[NormalizedSkill] = Field(default_factory=list)


class JobAnalysisResponse(BaseModel):
    """Response for JD analysis."""
    id: int
    job_description: JobDescription


class MatchRequest(BaseModel):
    """Request for matching (when using IDs)."""
    model_config = {"extra": "forbid"}
    resume_id: int = Field(gt=0, description="Positive integer resume ID")
    job_id: int = Field(gt=0, description="Positive integer job ID")


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    version: str = "1.0.0"
    gemini_available: bool = False
    embedding_model_loaded: bool = False
