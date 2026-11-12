"""Resume quality scoring engine (Rule-based 0-100, explainable).

Breakdown:
- Completeness (20)
- Impact (25)
- Skills (15)
- Clarity and length (15)
- ATS-friendliness (15)
- Professional links (10)

Also generates actionable improvement suggestions and missing role-based skills.
Optional: LLM-assisted bullet rewrites for up to 5 weakest bullets.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.config import get_settings
from app.schemas import (
    ImprovementSuggestion,
    NormalizedSkill,
    QualityComponent,
    QualityReport,
    ResumeProfile,
    Severity,
)
from app.services.skills import infer_role, get_skills_for_role

logger = logging.getLogger(__name__)

# Action verbs indicating high impact
STRONG_ACTION_VERBS = {
    "accelerated", "achieved", "analyzed", "architected", "automated", "built",
    "centralized", "championed", "collaborated", "conceived", "consolidated",
    "created", "decreased", "delivered", "deployed", "designed", "developed",
    "devised", "directed", "eliminated", "engineered", "established", "executed",
    "expanded", "expedited", "generated", "implemented", "improved", "increased",
    "initiated", "instituted", "integrated", "introduced", "launched", "led",
    "maximized", "mentored", "minimized", "modernized", "negotiated", "optimized",
    "orchestrated", "overhauled", "pioneered", "reduced", "re-engineered",
    "restructured", "scaled", "simplified", "spearheaded", "standardized",
    "streamlined", "strengthened", "transformed", "upgraded", "yielded"
}

WEAK_PHRASES = [
    "responsible for", "duties included", "helped with", "assisted in",
    "worked on", "participated in", "tasked with", "handled", "served as",
    "involved in", "support for", "daily tasks"
]

METRIC_PATTERN = re.compile(
    r"(?:\d+(?:\.\d+)?%|\$\d+(?:,\d{3})*(?:\.\d+)?(?:k|m|b)?|\b\d+(?:,\d{3})*\+?\b|\b\d+x\b)",
    re.IGNORECASE
)


def _score_completeness(profile: ResumeProfile) -> tuple[float, str, list[ImprovementSuggestion]]:
    """Score completeness (max 20 pts)."""
    score = 0.0
    details = []
    suggestions: list[ImprovementSuggestion] = []

    # Contact info (5 pts): email (2), phone (2), name (1)
    contact_pts = 0.0
    if profile.candidate.name:
        contact_pts += 1.0
    if profile.candidate.email:
        contact_pts += 2.0
    else:
        suggestions.append(ImprovementSuggestion(
            category="Completeness",
            severity=Severity.HIGH,
            issue="Missing professional email address.",
            fix="Add a clean, professional email (e.g., name@domain.com) at the very top of your resume."
        ))

    if profile.candidate.phone:
        contact_pts += 2.0
    else:
        suggestions.append(ImprovementSuggestion(
            category="Completeness",
            severity=Severity.MEDIUM,
            issue="Missing phone number.",
            fix="Include a current phone number with country code for recruiter outreach."
        ))

    score += contact_pts
    details.append(f"Contact info: {contact_pts:.1f}/5.0")

    # Summary (3 pts)
    if profile.summary and len(profile.summary.strip()) >= 40:
        score += 3.0
        details.append("Summary: 3.0/3.0")
    else:
        details.append("Summary: 0.0/3.0")
        suggestions.append(ImprovementSuggestion(
            category="Completeness",
            severity=Severity.MEDIUM,
            issue="Missing or very brief professional summary.",
            fix="Add a 2-3 sentence executive summary highlighting your years of experience, core technical specialties, and biggest accomplishments."
        ))

    # Education (4 pts)
    if profile.education and len(profile.education) > 0:
        score += 4.0
        details.append("Education: 4.0/4.0")
    else:
        details.append("Education: 0.0/4.0")
        suggestions.append(ImprovementSuggestion(
            category="Completeness",
            severity=Severity.HIGH,
            issue="No education section detected.",
            fix="Include your degrees, institutions, and graduation years under a dedicated 'Education' header."
        ))

    # Experience / Projects (4 pts)
    if profile.experience and len(profile.experience) > 0:
        score += 4.0
        details.append("Experience: 4.0/4.0")
    elif profile.projects and len(profile.projects) > 0:
        score += 3.0
        details.append("Projects: 3.0/4.0 (No formal experience)")
    else:
        details.append("Experience/Projects: 0.0/4.0")
        suggestions.append(ImprovementSuggestion(
            category="Completeness",
            severity=Severity.HIGH,
            issue="Missing both Work Experience and Projects sections.",
            fix="Detail your professional experience or technical portfolio projects with bullet points."
        ))

    # Skills section present (4 pts)
    if profile.skills_raw and len(profile.skills_raw) >= 3:
        score += 4.0
        details.append("Skills section: 4.0/4.0")
    else:
        details.append("Skills section: 0.0/4.0")
        suggestions.append(ImprovementSuggestion(
            category="Completeness",
            severity=Severity.HIGH,
            issue="No explicit skills section found.",
            fix="Add a 'Skills' or 'Technical Skills' section listing your programming languages, tools, and platforms."
        ))

    return score, "; ".join(details), suggestions


def _score_impact(profile: ResumeProfile) -> tuple[float, str, list[ImprovementSuggestion], list[str]]:
    """Score impact and action orientation (max 25 pts)."""
    all_bullets: list[str] = []
    for exp in profile.experience:
        all_bullets.extend(exp.bullets)
    for proj in profile.projects:
        if proj.description:
            # Split description if multiline
            lines = [l.strip().lstrip("-•") for l in proj.description.split("\n") if l.strip()]
            all_bullets.extend(lines)

    if not all_bullets:
        return 0.0, "No bullet points found in experience or projects", [
            ImprovementSuggestion(
                category="Impact",
                severity=Severity.HIGH,
                issue="Resume lacks descriptive bullet points.",
                fix="Use bullet points starting with strong action verbs and concrete metrics for each role."
            )
        ], []

    # 1. Share of bullets with metrics (max 15 pts)
    bullets_with_metrics = [b for b in all_bullets if METRIC_PATTERN.search(b)]
    metric_ratio = len(bullets_with_metrics) / len(all_bullets)
    metric_score = min(15.0, metric_ratio * 30.0)  # 50% bullets with metrics gives full 15 pts

    # 2. Action verbs vs weak phrases (max 10 pts)
    strong_count = 0
    weak_count = 0
    weak_bullets: list[str] = []

    for b in all_bullets:
        b_lower = b.lower().strip()
        first_word = b_lower.split()[0] if b_lower.split() else ""
        first_word_clean = re.sub(r"[^\w]", "", first_word)

        if first_word_clean in STRONG_ACTION_VERBS:
            strong_count += 1

        is_weak = False
        for wp in WEAK_PHRASES:
            if wp in b_lower:
                weak_count += 1
                is_weak = True
                break
        if is_weak:
            weak_bullets.append(b)

    verb_score = 10.0 * (strong_count / max(1, len(all_bullets))) - (2.0 * weak_count)
    verb_score = max(0.0, min(10.0, verb_score))

    total_score = metric_score + verb_score
    details = f"{len(bullets_with_metrics)}/{len(all_bullets)} bullets with metrics ({metric_score:.1f}/15); {strong_count} strong verbs, {weak_count} weak phrases ({verb_score:.1f}/10)"

    suggestions: list[ImprovementSuggestion] = []
    if metric_ratio < 0.3:
        suggestions.append(ImprovementSuggestion(
            category="Impact",
            severity=Severity.HIGH,
            issue=f"Only {int(metric_ratio * 100)}% of your experience bullets contain quantifiable metrics.",
            fix="Quantify your achievements using numbers, percentages, dollar amounts, or time savings (e.g., 'Reduced query latency by 45%', 'Serving 2M+ users').",
            rewritten_example="Worked on database optimization → Optimized PostgreSQL query execution plans, reducing p99 latency by 42% across 10M daily requests."
        ))

    if weak_count > 0:
        suggestions.append(ImprovementSuggestion(
            category="Impact",
            severity=Severity.MEDIUM,
            issue=f"Found {weak_count} bullet(s) using passive or weak phrases (e.g., 'responsible for', 'worked on').",
            fix="Replace passive phrases with strong, outcome-driven action verbs (e.g., 'Architected', 'Spearheaded', 'Optimized').",
            rewritten_example="Responsible for team tasks → Spearheaded sprint deliverables and coordinated cross-functional execution for 6 engineers."
        ))

    return total_score, details, suggestions, weak_bullets[:5]


def _score_skills(profile: ResumeProfile, normalized_skills: list[NormalizedSkill]) -> tuple[float, str, list[ImprovementSuggestion]]:
    """Score skills number and diversity (max 15 pts)."""
    tech_skills = [s for s in normalized_skills if s.category.value == "technical"]
    soft_skills = [s for s in normalized_skills if s.category.value == "soft"]

    # Count score (max 10 pts)
    # 15+ skills is optimal (10 pts), 8-14 (7 pts), 4-7 (4 pts), <4 (2 pts)
    count = len(normalized_skills)
    if count >= 15:
        count_score = 10.0
    elif count >= 10:
        count_score = 8.0
    elif count >= 6:
        count_score = 6.0
    elif count >= 3:
        count_score = 3.0
    else:
        count_score = 1.0

    # Diversity score (max 5 pts)
    # Check if candidate has both technical and soft or multiple skill domains
    diversity_score = 0.0
    if len(tech_skills) >= 5:
        diversity_score += 3.0
    elif len(tech_skills) >= 2:
        diversity_score += 1.5

    if len(soft_skills) >= 1:
        diversity_score += 2.0

    total_score = min(15.0, count_score + diversity_score)
    details = f"{count} skills detected ({len(tech_skills)} technical, {len(soft_skills)} soft)"

    suggestions: list[ImprovementSuggestion] = []
    if count < 8:
        suggestions.append(ImprovementSuggestion(
            category="Skills",
            severity=Severity.HIGH,
            issue=f"Only {count} skills identified on the resume.",
            fix="Expand your skills section with relevant frameworks, libraries, tools, cloud platforms, and databases you have used."
        ))

    if len(soft_skills) == 0:
        suggestions.append(ImprovementSuggestion(
            category="Skills",
            severity=Severity.LOW,
            issue="No interpersonal or soft skills explicitly highlighted.",
            fix="Weave soft skills such as 'Cross-functional Collaboration', 'Technical Leadership', or 'Agile Delivery' into your bullets or summary."
        ))

    return total_score, details, suggestions


def _score_clarity_and_length(profile: ResumeProfile, raw_text: str) -> tuple[float, str, list[ImprovementSuggestion]]:
    """Score clarity, readability, and brevity (max 15 pts)."""
    score = 15.0
    details = []
    suggestions: list[ImprovementSuggestion] = []

    words = raw_text.split()
    word_count = len(words)

    # Ideal resume length: ~300 to 900 words (~1-2 pages)
    if word_count < 150:
        score -= 6.0
        details.append(f"Very brief ({word_count} words)")
        suggestions.append(ImprovementSuggestion(
            category="Clarity and Length",
            severity=Severity.HIGH,
            issue=f"Resume is extremely short ({word_count} words).",
            fix="Add detailed bullet points to your work history and project descriptions to showcase your expertise."
        ))
    elif word_count > 1200:
        score -= 4.0
        details.append(f"Excessive length ({word_count} words)")
        suggestions.append(ImprovementSuggestion(
            category="Clarity and Length",
            severity=Severity.MEDIUM,
            issue=f"Resume is quite long ({word_count} words, ~3+ pages).",
            fix="Condense older or less relevant roles to focus on recent accomplishments and maintain a 1-2 page standard."
        ))
    else:
        details.append(f"Optimal length ({word_count} words)")

    # Check for wall of text (paragraphs longer than 150 words)
    paragraphs = raw_text.split("\n\n")
    long_paragraphs = [p for p in paragraphs if len(p.split()) > 100 and not p.strip().startswith("-")]
    if len(long_paragraphs) > 0:
        score -= 3.0
        details.append(f"{len(long_paragraphs)} wall(s) of text detected")
        suggestions.append(ImprovementSuggestion(
            category="Clarity and Length",
            severity=Severity.MEDIUM,
            issue="Large blocks of dense text found.",
            fix="Break long paragraphs into punchy, 1-2 line bullet points for quick recruiter skimming."
        ))

    # Check bullet length
    all_bullets: list[str] = []
    for exp in profile.experience:
        all_bullets.extend(exp.bullets)
    for proj in profile.projects:
        if proj.description:
            all_bullets.extend(proj.description.split("\n"))

    if all_bullets:
        long_bullets = [b for b in all_bullets if len(b.split()) > 45]
        if len(long_bullets) > 2:
            score -= 2.0
            details.append(f"{len(long_bullets)} overly long bullets")
            suggestions.append(ImprovementSuggestion(
                category="Clarity and Length",
                severity=Severity.LOW,
                issue="Some bullet points are too wordy (>45 words).",
                fix="Keep each bullet focused on a single key outcome. Target 15-30 words per bullet."
            ))

    score = max(0.0, score)
    return score, "; ".join(details), suggestions


def _score_ats_friendliness(profile: ResumeProfile, raw_text: str) -> tuple[float, str, list[ImprovementSuggestion]]:
    """Score ATS-friendliness (max 15 pts)."""
    score = 15.0
    details = []
    suggestions: list[ImprovementSuggestion] = []

    # Check for standard section headings
    headers_found = 0
    standard_headers = ["EXPERIENCE", "EDUCATION", "SKILLS", "SUMMARY", "PROJECTS"]
    text_upper = raw_text.upper()
    for sh in standard_headers:
        if sh in text_upper:
            headers_found += 1

    if headers_found < 3:
        score -= 5.0
        details.append(f"Only {headers_found}/5 standard headings found")
        suggestions.append(ImprovementSuggestion(
            category="ATS-Friendliness",
            severity=Severity.HIGH,
            issue="Missing standard ATS section headings (e.g., 'Experience', 'Education', 'Skills').",
            fix="Use standard, universally recognizable headings so Applicant Tracking Systems can parse each section correctly."
        ))
    else:
        details.append(f"{headers_found}/5 standard headings present")

    # Check for date consistency in experience
    has_dates = 0
    for exp in profile.experience:
        if exp.start or exp.end:
            has_dates += 1
    if profile.experience and has_dates < len(profile.experience):
        score -= 3.0
        details.append("Inconsistent work dates")
        suggestions.append(ImprovementSuggestion(
            category="ATS-Friendliness",
            severity=Severity.MEDIUM,
            issue="Some experience entries are missing start and end dates.",
            fix="Ensure all work experiences list clear dates (e.g., 'Jan 2021 - Present')."
        ))

    score = max(0.0, score)
    return score, "; ".join(details), suggestions


def _score_professional_links(profile: ResumeProfile) -> tuple[float, str, list[ImprovementSuggestion]]:
    """Score professional links (LinkedIn & GitHub/Portfolio) (max 10 pts)."""
    score = 0.0
    details = []
    suggestions: list[ImprovementSuggestion] = []

    # LinkedIn (5 pts)
    if profile.candidate.linkedin:
        score += 5.0
        details.append("LinkedIn: 5.0/5.0")
    else:
        suggestions.append(ImprovementSuggestion(
            category="Professional Links",
            severity=Severity.MEDIUM,
            issue="No LinkedIn profile URL provided.",
            fix="Add your personalized LinkedIn profile link in the contact header."
        ))
        details.append("LinkedIn: 0.0/5.0")

    # GitHub / Portfolio (5 pts)
    if profile.candidate.github:
        score += 5.0
        details.append("GitHub: 5.0/5.0")
    elif profile.candidate.portfolio:
        score += 5.0
        details.append("Portfolio: 5.0/5.0")
    else:
        suggestions.append(ImprovementSuggestion(
            category="Professional Links",
            severity=Severity.LOW,
            issue="No GitHub or Portfolio URL provided.",
            fix="Include a GitHub, GitLab, or personal portfolio link to showcase your public code and projects."
        ))
        details.append("GitHub/Portfolio: 0.0/5.0")

    return score, "; ".join(details), suggestions


def _rewrite_bullets_with_gemini(weak_bullets: list[str]) -> dict[str, str]:
    """Optionally rewrite weak bullets using Gemini. Skipped if no key."""
    settings = get_settings()
    if not settings.has_gemini_key or not weak_bullets:
        return {}

    try:
        from google import genai
        client = genai.Client(api_key=settings.gemini_api_key)
        bullets_text = "\n".join(f"- {b}" for b in weak_bullets)
        prompt = f"""Rewrite each of the following weak resume bullets to make them high-impact.
Use the Google X-Y-Z formula: "Accomplished [X], as measured by [Y], by doing [Z]".
Start with a strong action verb and include plausible placeholder metrics in brackets if none exist.
Return a valid JSON object mapping the original bullet to the rewritten bullet.

BULLETS:
{bullets_text}"""

        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config={"response_mime_type": "application/json", "temperature": 0.2}
        )
        return json.loads(response.text)
    except Exception as exc:
        logger.warning("Bullet rewrite with Gemini failed: %s", exc)
        return {}


def score_resume_quality(
    profile: ResumeProfile,
    normalized_skills: list[NormalizedSkill],
    raw_text: str = "",
) -> QualityReport:
    """Compute deterministic resume quality score (0-100) with explainable breakdown.

    Args:
        profile: Extracted resume profile.
        normalized_skills: List of normalized skills found across sections.
        raw_text: Raw or cleaned resume text for length/clarity checks.

    Returns:
        Structured QualityReport.
    """
    comp_score, comp_details, comp_sugg = _score_completeness(profile)
    impact_score, impact_details, impact_sugg, weak_bullets = _score_impact(profile)
    skills_score, skills_details, skills_sugg = _score_skills(profile, normalized_skills)
    clarity_score, clarity_details, clarity_sugg = _score_clarity_and_length(profile, raw_text)
    ats_score, ats_details, ats_sugg = _score_ats_friendliness(profile, raw_text)
    links_score, links_details, links_sugg = _score_professional_links(profile)

    overall = comp_score + impact_score + skills_score + clarity_score + ats_score + links_score
    overall = round(max(0.0, min(100.0, overall)), 1)

    components = [
        QualityComponent(name="Completeness", score=round(comp_score, 1), max_score=20.0, details=comp_details),
        QualityComponent(name="Impact & Metrics", score=round(impact_score, 1), max_score=25.0, details=impact_details),
        QualityComponent(name="Skills Diversity", score=round(skills_score, 1), max_score=15.0, details=skills_details),
        QualityComponent(name="Clarity & Length", score=round(clarity_score, 1), max_score=15.0, details=clarity_details),
        QualityComponent(name="ATS-Friendliness", score=round(ats_score, 1), max_score=15.0, details=ats_details),
        QualityComponent(name="Professional Links", score=round(links_score, 1), max_score=10.0, details=links_details),
    ]

    all_suggestions = comp_sugg + impact_sugg + skills_sugg + clarity_sugg + ats_sugg + links_sugg

    # Optional Gemini bullet rewrites
    if weak_bullets:
        rewrites = _rewrite_bullets_with_gemini(weak_bullets)
        for s in all_suggestions:
            if s.category == "Impact" and s.rewritten_example is None and rewrites:
                # Attach rewritten example if available
                first_k = next(iter(rewrites))
                s.rewritten_example = f"{first_k} → {rewrites[first_k]}"

    # Inferred role and missing skills
    inferred = infer_role(normalized_skills)
    expected_skills = get_skills_for_role(inferred)
    candidate_skills = {s.normalized.lower() for s in normalized_skills}
    missing_skills = [
        s for s in expected_skills if s.lower() not in candidate_skills
    ]

    return QualityReport(
        overall_score=overall,
        components=components,
        improvement_suggestions=all_suggestions,
        missing_skills_for_role=missing_skills[:8],  # Top missing skills
        inferred_role=inferred,
    )
