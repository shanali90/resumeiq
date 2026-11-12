"""Job description analyzer — extract structured requirements from raw text.

Extracts:
- title, seniority
- required_skills[] vs preferred_skills[] (distinguished via cues)
- min_experience_years
- education_requirement
- responsibilities[]
- domain_keywords[]

Primary: Gemini API structured output with strict JSON schema.
Fallback: Rule-based parsing with keyword cues and skills taxonomy.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.config import get_settings
from app.schemas import ExtractionMode, JobDescription
from app.services.skills import normalize_skills, normalize_skill, SkillCategory

logger = logging.getLogger(__name__)

# JSON schema for Gemini JD extraction
JD_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "nullable": True},
        "seniority": {"type": "string", "nullable": True},
        "required_skills": {
            "type": "array",
            "items": {"type": "string"},
        },
        "preferred_skills": {
            "type": "array",
            "items": {"type": "string"},
        },
        "min_experience_years": {"type": "integer", "nullable": True},
        "education_requirement": {"type": "string", "nullable": True},
        "responsibilities": {
            "type": "array",
            "items": {"type": "string"},
        },
        "domain_keywords": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}

JD_PROMPT = """You are an expert technical recruiter analyzing a job description.
Extract structured requirements from the job description text below.

RULES:
- Distinguish strictly between required_skills (must-have, essential, mandatory) and preferred_skills (nice-to-have, plus, bonus, preferred).
- If a skill mentions "(plus)", "(nice to have)", or "preferred", place it in preferred_skills.
- Extract only skills and requirements explicitly stated.
- Extract min_experience_years as a single integer (e.g., 5 for "5+ years").
- Extract seniority (e.g., "Senior", "Junior", "Mid-Level", "Lead", "Staff", "Entry-Level").
- Extract education_requirement (e.g., "BS/MS in Computer Science or related field").

JOB DESCRIPTION:
{text}"""


def extract_jd_with_gemini(text: str) -> JobDescription:
    """Extract job description structure using Gemini API."""
    settings = get_settings()

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=settings.gemini_api_key)
    prompt = JD_PROMPT.format(text=text)

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=JD_SCHEMA,
        temperature=0,
    )

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = client.models.generate_content(
                model=settings.gemini_model,
                contents=prompt,
                config=config,
            )
            data = json.loads(response.text)

            # Normalize skills through taxonomy
            raw_req = data.get("required_skills", [])
            raw_pref = data.get("preferred_skills", [])

            norm_req = [s.normalized for s in normalize_skills(raw_req)]
            norm_pref = [s.normalized for s in normalize_skills(raw_pref)]

            return JobDescription(
                title=data.get("title"),
                seniority=data.get("seniority"),
                required_skills=norm_req,
                preferred_skills=norm_pref,
                min_experience_years=data.get("min_experience_years"),
                education_requirement=data.get("education_requirement"),
                responsibilities=data.get("responsibilities", []),
                domain_keywords=data.get("domain_keywords", []),
                extraction_mode=ExtractionMode.LLM,
            )
        except Exception as exc:
            last_error = exc
            logger.warning("Gemini JD extraction failed on attempt %d: %s", attempt + 1, exc)

    raise Exception(f"Gemini JD extraction failed: {last_error}")


# ── Rule-Based JD Extractor ──────────────────────────────────────────

EXPERIENCE_PATTERN = re.compile(
    r"(?:(?:experience|exp)[\s:]+(\d+)\+?\s*(?:-\s*\d+)?\s*years?|"
    r"(\d+)\+?\s*(?:-\s*\d+)?\s*years?(?:\s*of)?\s*(?:relevant\s*)?(?:experience|work))",
    re.IGNORECASE
)

SENIORITY_KEYWORDS = {
    "entry": "Entry-Level",
    "junior": "Junior",
    "mid": "Mid-Level",
    "senior": "Senior",
    "sr": "Senior",
    "lead": "Lead",
    "principal": "Principal",
    "staff": "Staff",
    "director": "Director",
    "head": "Head of Engineering",
}

EDUCATION_KEYWORDS = [
    "phd", "ph.d", "master's", "masters", "ms", "m.s.", "bachelor's", "bachelors",
    "bs", "b.s.", "degree", "computer science", "mathematics"
]

PREFERRED_CUES = [
    "nice to have", "plus", "pluses", "bonus", "preferred", "preferable",
    "good to have", "helpful", "desirable", "optional"
]

REQUIRED_CUES = [
    "must have", "must-have", "required", "requirements", "essential",
    "mandatory", "qualifications", "minimum qualifications", "core skills"
]


def extract_jd_rule_based(text: str) -> JobDescription:
    """Extract job description requirements using rule-based parsing."""
    logger.info("Using rule-based JD analysis")

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    title = lines[0] if lines else "Target Position"

    # Infer seniority
    seniority = None
    for token in title.lower().split() + text.lower()[:300].split():
        clean_token = re.sub(r"[^\w]", "", token)
        if clean_token in SENIORITY_KEYWORDS:
            seniority = SENIORITY_KEYWORDS[clean_token]
            break

    # Infer minimum experience
    exp_match = EXPERIENCE_PATTERN.search(text)
    min_exp = None
    if exp_match:
        val = exp_match.group(1) or exp_match.group(2)
        if val:
            min_exp = int(val)

    # Education requirement
    edu_req = None
    for line in lines:
        line_lower = line.lower()
        if any(w in line_lower for w in ["degree", "bachelor", "master", "phd", "ms in", "bs in"]):
            edu_req = line.lstrip("-•*").strip()
            break

    # Split into required vs preferred sections or inspect line cues
    required_raw: list[str] = []
    preferred_raw: list[str] = []
    responsibilities: list[str] = []

    current_section = "general"

    for line in lines:
        line_clean = line.lstrip("-•* ").strip()
        line_lower = line.lower()
        is_bullet = line.startswith(("-", "•", "*"))

        # Section header switches (only on non-bullet lines)
        if not is_bullet:
            if any(h in line_lower for h in ["preferred skill", "preferred qualification", "nice to have", "bonus", "pluses"]):
                current_section = "preferred"
                continue
            elif any(h in line_lower for h in ["required skill", "basic qualification", "minimum qualification", "requirements", "must have"]):
                current_section = "required"
                continue
            elif any(h in line_lower for h in ["responsibilities", "what you'll do", "duties", "the role"]):
                current_section = "responsibilities"
                continue
            elif any(h in line_lower for h in ["education", "about the role", "company", "location"]):
                current_section = "other"
                continue

        # Process lines within sections
        if line.startswith(("-", "•", "*")) or current_section in ("required", "preferred", "responsibilities"):
            # Check for inline cues
            is_pref_cue = any(c in line_lower for c in PREFERRED_CUES)
            is_req_cue = any(c in line_lower for c in REQUIRED_CUES)

            if current_section == "responsibilities":
                responsibilities.append(line_clean)
            elif is_pref_cue or current_section == "preferred":
                preferred_raw.append(line_clean)
            elif is_req_cue or current_section == "required":
                required_raw.append(line_clean)

    # Normalize skills found in raw strings
    def _clean_skill_chunk(chunk: str) -> str:
        # Remove parenthetical cues e.g. (must have), (plus), (required)
        c = re.sub(r"\(.*?\)", "", chunk).strip().lstrip("-•* ")
        return c

    norm_required_dict = {}
    for r in required_raw:
        for chunk in re.split(r"[,|;/]|(?:\bor\b)", r):
            cleaned = _clean_skill_chunk(chunk)
            if not cleaned or len(cleaned) > 40:
                continue
            res = normalize_skill(cleaned)
            if res:
                norm_required_dict[res[0]] = True

    norm_preferred_dict = {}
    for p in preferred_raw:
        for chunk in re.split(r"[,|;/]|(?:\bor\b)", p):
            cleaned = _clean_skill_chunk(chunk)
            if not cleaned or len(cleaned) > 40:
                continue
            res = normalize_skill(cleaned)
            if res and res[0] not in norm_required_dict:
                norm_preferred_dict[res[0]] = True

    # If few skills were found from sections, scan full text for skills
    if len(norm_required_dict) < 3:
        all_skills = normalize_skills(lines)
        for s in all_skills:
            if s.category == SkillCategory.TECHNICAL and s.normalized not in norm_required_dict:
                norm_required_dict[s.normalized] = True

    # Domain keywords: extract notable tech terms
    domain_keywords = list(norm_required_dict.keys()) + list(norm_preferred_dict.keys())

    return JobDescription(
        title=title,
        seniority=seniority,
        required_skills=list(norm_required_dict.keys()),
        preferred_skills=list(norm_preferred_dict.keys()),
        min_experience_years=min_exp,
        education_requirement=edu_req,
        responsibilities=responsibilities[:8],
        domain_keywords=domain_keywords[:12],
        extraction_mode=ExtractionMode.RULE_BASED,
    )


def analyze_job_description(text: str) -> JobDescription:
    """Analyze job description text using Gemini or fallback."""
    settings = get_settings()

    if settings.has_gemini_key:
        try:
            return extract_jd_with_gemini(text)
        except Exception as exc:
            logger.warning("Gemini JD analysis failed, falling back to rule-based: %s", exc)

    return extract_jd_rule_based(text)
