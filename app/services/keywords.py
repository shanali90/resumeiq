"""Keyword optimization and ATS gap analysis using TF-IDF and term frequency.

Finds important JD keywords missing from the resume, suggests natural
insertion points without keyword stuffing, and calculates an ATS match percentage.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer

from app.schemas import KeywordAnalysis, KeywordGap

logger = logging.getLogger(__name__)

STOP_WORDS = {
    "and", "the", "to", "of", "in", "for", "with", "a", "an", "on", "at", "by",
    "from", "as", "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "but", "if", "or", "because", "as", "until", "while",
    "about", "against", "between", "into", "through", "during", "before", "after",
    "above", "below", "up", "down", "out", "off", "over", "under", "again", "further",
    "then", "once", "here", "there", "when", "where", "why", "how", "all", "any",
    "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "can", "will", "just",
    "should", "now", "our", "we", "you", "your", "they", "their", "role", "team",
    "work", "looking", "join", "years", "experience", "candidate", "responsibilities",
    "requirements", "qualifications", "preferred", "required", "company", "location"
}


def analyze_keywords(resume_text: str, jd_text: str) -> KeywordAnalysis:
    """Analyze keyword overlap between resume and JD using TF-IDF.

    Args:
        resume_text: Clean extracted resume text.
        jd_text: Full job description text.

    Returns:
        Structured KeywordAnalysis with ATS match % and missing keywords.
    """
    if not resume_text.strip() or not jd_text.strip():
        return KeywordAnalysis(
            ats_match_percentage=0.0,
            matched_keywords=[],
            missing_keywords=[],
        )

    # Clean up multi-lines into clean sentences/paragraphs to avoid bad n-grams
    clean_jd = " . ".join(line.strip() for line in jd_text.split("\n") if line.strip())

    # 1. Fit TF-IDF on the JD to discover high-importance terms
    vectorizer = TfidfVectorizer(
        ngram_range=(1, 1),  # Focus on clean domain keywords
        stop_words=list(STOP_WORDS),
        token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z0-9_\-\+\#\.]{2,24}\b",
        max_features=40,
    )

    try:
        tfidf_matrix = vectorizer.fit_transform([clean_jd])
        feature_names = vectorizer.get_feature_names_out()
        scores = tfidf_matrix.toarray()[0]
    except ValueError as exc:
        logger.warning("TF-IDF extraction failed: %s", exc)
        return KeywordAnalysis(
            ats_match_percentage=50.0,
            matched_keywords=[],
            missing_keywords=[],
        )

    # Pair features with scores and filter out noise
    term_scores: list[tuple[str, float]] = []
    for term, score in zip(feature_names, scores):
        clean_term = term.strip().lower()
        if len(clean_term) >= 3 and score > 0.05:
            term_scores.append((clean_term, float(score)))

    term_scores.sort(key=lambda x: x[1], reverse=True)

    # Normalize scores to 0-1
    max_score = term_scores[0][1] if term_scores else 1.0

    matched: list[str] = []
    missing: list[KeywordGap] = []
    resume_lower = resume_text.lower()

    for term, raw_score in term_scores[:30]:
        normalized_importance = round(raw_score / max_score, 2)
        pattern = r"\b" + re.escape(term) + r"\b"

        if re.search(pattern, resume_lower):
            matched.append(term)
        else:
            # Generate natural placement suggestions
            if any(tech in term for tech in ["pipeline", "model", "api", "database", "query", "deploy", "ci/cd", "cloud"]):
                suggestion = (
                    f"Mention '{term}' in your relevant experience bullets or technical project descriptions."
                )
            elif any(verb in term for verb in ["leading", "collaborate", "agile", "cross-functional"]):
                suggestion = (
                    f"Integrate '{term}' into your summary or team collaboration bullet points."
                )
            else:
                suggestion = (
                    f"Naturally reference '{term}' where applicable in your skills or experience sections."
                )

            missing.append(KeywordGap(
                keyword=term,
                importance=normalized_importance,
                suggestion=suggestion,
            ))

    total_terms = len(matched) + len(missing)
    ats_pct = round((len(matched) / max(1, total_terms)) * 100, 1)

    return KeywordAnalysis(
        ats_match_percentage=ats_pct,
        matched_keywords=matched,
        missing_keywords=missing[:10],  # Top 10 missing
    )
