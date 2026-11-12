"""Skill normalization, categorization, and detection.

Loads a taxonomy of 500+ skills with aliases, normalizes raw skill
strings via exact match → alias match → fuzzy match, classifies
each as technical or soft, and detects skills from free text.
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz, process

from app.config import get_settings
from app.schemas import NormalizedSkill, SkillCategory, SkillSource

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_taxonomy() -> dict:
    """Load skills taxonomy from JSON file (cached).

    Returns:
        Full taxonomy dict with categories and skills.
    """
    settings = get_settings()
    taxonomy_path = settings.taxonomy_path

    if not taxonomy_path.exists():
        logger.warning("Skills taxonomy not found at %s", taxonomy_path)
        return {"categories": {}}

    with open(taxonomy_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    logger.info("Loaded skills taxonomy with %d categories", len(data.get("categories", {})))
    return data


def _build_lookup_tables() -> tuple[dict[str, str], dict[str, SkillCategory], list[str]]:
    """Build fast lookup tables from the taxonomy.

    Returns:
        Tuple of (alias_to_canonical, canonical_to_category, all_canonical_names).
    """
    taxonomy = _load_taxonomy()
    alias_to_canonical: dict[str, str] = {}
    canonical_to_category: dict[str, SkillCategory] = {}
    all_names: list[str] = []

    for cat_key, cat_data in taxonomy.get("categories", {}).items():
        cat_type = SkillCategory.SOFT if cat_data.get("type") == "soft" else SkillCategory.TECHNICAL
        skills = cat_data.get("skills", {})

        for skill_name, skill_info in skills.items():
            canonical = skill_name
            canonical_lower = canonical.lower()

            # Map canonical name
            alias_to_canonical[canonical_lower] = canonical
            canonical_to_category[canonical] = cat_type
            all_names.append(canonical)

            # Map all aliases
            for alias in skill_info.get("aliases", []):
                alias_to_canonical[alias.lower()] = canonical

    return alias_to_canonical, canonical_to_category, all_names


# Cache the lookup tables
_lookup_cache: dict | None = None


def _get_lookups() -> tuple[dict[str, str], dict[str, SkillCategory], list[str]]:
    """Get cached lookup tables."""
    global _lookup_cache
    if _lookup_cache is None:
        alias_map, cat_map, names = _build_lookup_tables()
        _lookup_cache = {
            "alias_to_canonical": alias_map,
            "canonical_to_category": cat_map,
            "all_names": names,
        }
    return (
        _lookup_cache["alias_to_canonical"],
        _lookup_cache["canonical_to_category"],
        _lookup_cache["all_names"],
    )


def normalize_skill(raw: str) -> tuple[str, SkillCategory] | None:
    """Normalize a single skill string to canonical form.

    Tries exact match, then alias match, then fuzzy match.

    Args:
        raw: Raw skill string from resume.

    Returns:
        Tuple of (canonical_name, category) or None if no match.
    """
    settings = get_settings()
    alias_to_canonical, canonical_to_category, all_names = _get_lookups()

    raw_clean = raw.strip()
    if not raw_clean:
        return None

    raw_lower = raw_clean.lower()

    # 1. Exact / alias match
    if raw_lower in alias_to_canonical:
        canonical = alias_to_canonical[raw_lower]
        return canonical, canonical_to_category[canonical]

    # 2. Fuzzy match (rapidfuzz)
    if all_names:
        result = process.extractOne(
            raw_clean,
            all_names,
            scorer=fuzz.ratio,
            score_cutoff=settings.fuzzy_match_threshold,
        )
        if result:
            matched_name, score, _ = result
            logger.debug(
                "Fuzzy matched '%s' → '%s' (score: %d)", raw, matched_name, score
            )
            return matched_name, canonical_to_category[matched_name]

    return None


def normalize_skills(
    raw_skills: list[str],
    source: SkillSource = SkillSource.SKILLS_SECTION,
) -> list[NormalizedSkill]:
    """Normalize a list of raw skill strings.

    Args:
        raw_skills: List of raw skill strings.
        source: Where these skills were found.

    Returns:
        List of NormalizedSkill objects (deduplicated by canonical name).
    """
    seen: dict[str, NormalizedSkill] = {}

    for raw in raw_skills:
        result = normalize_skill(raw)
        if result:
            canonical, category = result
            if canonical in seen:
                # Add source if not already present
                if source not in seen[canonical].sources:
                    seen[canonical].sources.append(source)
            else:
                seen[canonical] = NormalizedSkill(
                    raw=raw.strip(),
                    normalized=canonical,
                    category=category,
                    sources=[source],
                )
        else:
            # Keep unmatched skills as-is, categorize as technical by default
            if raw.strip() and raw.strip() not in seen:
                seen[raw.strip()] = NormalizedSkill(
                    raw=raw.strip(),
                    normalized=raw.strip(),
                    category=SkillCategory.TECHNICAL,
                    sources=[source],
                )

    return list(seen.values())


def detect_skills_in_text(
    text: str,
    source: SkillSource = SkillSource.EXPERIENCE,
) -> list[NormalizedSkill]:
    """Detect skills mentioned in free text (experience, projects, etc.).

    Uses word-boundary matching against the taxonomy.

    Args:
        text: Free text to scan.
        source: Source label for detected skills.

    Returns:
        List of NormalizedSkill objects found in text.
    """
    alias_to_canonical, canonical_to_category, all_names = _get_lookups()
    found: dict[str, NormalizedSkill] = {}

    if not text:
        return []

    text_lower = text.lower()

    # Check all aliases and canonical names
    for alias_lower, canonical in alias_to_canonical.items():
        if len(alias_lower) < 2:
            continue  # Skip single-char aliases to avoid false positives

        # Use word boundary matching for short terms
        if len(alias_lower) <= 3:
            pattern = r"\b" + re.escape(alias_lower) + r"\b"
            if re.search(pattern, text_lower):
                if canonical not in found:
                    found[canonical] = NormalizedSkill(
                        raw=alias_lower,
                        normalized=canonical,
                        category=canonical_to_category[canonical],
                        sources=[source],
                    )
        else:
            # For longer terms, simple substring with word boundaries
            if alias_lower in text_lower:
                # Verify it's not part of a larger word
                idx = text_lower.find(alias_lower)
                before = text_lower[idx - 1] if idx > 0 else " "
                after = text_lower[idx + len(alias_lower)] if idx + len(alias_lower) < len(text_lower) else " "

                if not before.isalnum() and not after.isalnum():
                    if canonical not in found:
                        found[canonical] = NormalizedSkill(
                            raw=alias_lower,
                            normalized=canonical,
                            category=canonical_to_category[canonical],
                            sources=[source],
                        )

    return list(found.values())


def merge_skills(
    *skill_lists: list[NormalizedSkill],
) -> list[NormalizedSkill]:
    """Merge multiple skill lists, combining sources for duplicates.

    Args:
        *skill_lists: Variable number of NormalizedSkill lists.

    Returns:
        Merged and deduplicated list.
    """
    merged: dict[str, NormalizedSkill] = {}

    for skill_list in skill_lists:
        for skill in skill_list:
            if skill.normalized in merged:
                existing = merged[skill.normalized]
                for src in skill.sources:
                    if src not in existing.sources:
                        existing.sources.append(src)
            else:
                merged[skill.normalized] = skill.model_copy(deep=True)

    return list(merged.values())


def get_skills_for_role(role: str) -> list[str]:
    """Get commonly expected skills for a given role.

    Args:
        role: Role name (e.g., "ML Engineer", "Web Developer").

    Returns:
        List of expected skill names for that role.
    """
    role_skills: dict[str, list[str]] = {
        "ML Engineer": [
            "Python", "PyTorch", "TensorFlow", "scikit-learn", "Machine Learning",
            "Deep Learning", "NLP", "Computer Vision", "Docker", "SQL", "Git",
            "AWS", "Pandas", "NumPy", "MLOps", "Statistics",
        ],
        "Data Scientist": [
            "Python", "R", "SQL", "Machine Learning", "Statistics",
            "Pandas", "NumPy", "scikit-learn", "Data Visualization",
            "Jupyter", "Tableau", "A/B Testing", "Feature Engineering",
        ],
        "Web Developer": [
            "JavaScript", "TypeScript", "React", "HTML", "CSS", "Node.js",
            "Git", "REST API", "SQL", "Docker", "Testing", "CI/CD",
        ],
        "Full Stack Developer": [
            "JavaScript", "TypeScript", "React", "Node.js", "SQL",
            "HTML", "CSS", "Git", "Docker", "REST API", "PostgreSQL",
            "Testing", "CI/CD", "Cloud",
        ],
        "Backend Developer": [
            "Python", "Java", "SQL", "PostgreSQL", "REST API", "Docker",
            "Git", "Kubernetes", "Redis", "Message Queues", "CI/CD",
        ],
        "Frontend Developer": [
            "JavaScript", "TypeScript", "React", "HTML", "CSS",
            "Tailwind CSS", "Git", "Testing", "Responsive Design",
            "Webpack", "Accessibility",
        ],
        "DevOps Engineer": [
            "Docker", "Kubernetes", "Terraform", "AWS", "CI/CD",
            "Linux", "Git", "Ansible", "Prometheus", "Grafana",
            "Jenkins", "Python", "Shell/Bash",
        ],
        "Data Engineer": [
            "Python", "SQL", "Apache Spark", "Airflow", "Docker",
            "AWS", "Kafka", "ETL", "Data Warehousing", "dbt",
            "PostgreSQL", "Git",
        ],
        "Mobile Developer": [
            "Kotlin", "Swift", "React Native", "Flutter", "Git",
            "REST API", "CI/CD", "Testing", "Firebase",
        ],
        "Software Engineer": [
            "Python", "Java", "Git", "SQL", "Docker", "REST API",
            "Testing", "CI/CD", "Data Structures", "Algorithms",
            "Linux", "Cloud",
        ],
    }

    role_lower = role.lower()
    for key, skills in role_skills.items():
        if key.lower() in role_lower or role_lower in key.lower():
            return skills

    # Default to Software Engineer
    return role_skills.get("Software Engineer", [])


def infer_role(skills: list[NormalizedSkill]) -> str:
    """Infer the dominant role from a candidate's skills.

    Uses skill-cluster overlap scoring.

    Args:
        skills: List of normalized skills.

    Returns:
        Inferred role name.
    """
    skill_names = {s.normalized.lower() for s in skills}

    role_indicators: dict[str, list[str]] = {
        "ML Engineer": ["machine learning", "deep learning", "pytorch", "tensorflow",
                        "nlp", "computer vision", "scikit-learn"],
        "Data Scientist": ["statistics", "r", "tableau", "data visualization",
                          "a/b testing", "jupyter"],
        "Web Developer": ["react", "javascript", "html", "css", "vue.js",
                         "angular", "next.js"],
        "Full Stack Developer": ["react", "node.js", "javascript", "postgresql",
                                "mongodb", "rest api"],
        "Backend Developer": ["java", "spring boot", "microservices", "kafka",
                             "redis", "postgresql"],
        "Frontend Developer": ["react", "css", "tailwind css", "webpack",
                              "typescript", "figma"],
        "DevOps Engineer": ["docker", "kubernetes", "terraform", "ansible",
                           "jenkins", "prometheus"],
        "Data Engineer": ["apache spark", "airflow", "etl", "data warehousing",
                         "kafka", "snowflake", "dbt"],
        "Mobile Developer": ["kotlin", "swift", "react native", "flutter",
                            "android sdk", "ios sdk"],
    }

    best_role = "Software Engineer"
    best_score = 0

    for role, indicators in role_indicators.items():
        score = sum(1 for ind in indicators if ind in skill_names)
        if score > best_score:
            best_score = score
            best_role = role

    return best_role
