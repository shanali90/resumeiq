"""Professional PDF and JSON report generation using ReportLab.

Generates:
1. Candidate Evaluation PDF: Header, match %, score breakdown table, strengths,
   weaknesses, skill gap table, recommendations, and ATS keywords.
2. Recruiter Summary PDF: Ranked candidate table, top-3 candidates, comparison matrix.
"""

from __future__ import annotations

import io
import logging
import xml.sax.saxutils as saxutils
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.schemas import KeywordAnalysis, MatchResult, RankingResult

logger = logging.getLogger(__name__)

# Color Palette
PRIMARY = colors.HexColor("#1E293B")   # Slate 800
SECONDARY = colors.HexColor("#334155") # Slate 700
ACCENT = colors.HexColor("#0284C7")    # Sky 600
SUCCESS = colors.HexColor("#16A34A")   # Green 600
WARNING = colors.HexColor("#D97706")   # Amber 600
DANGER = colors.HexColor("#DC2626")    # Red 600
LIGHT_BG = colors.HexColor("#F8FAFC")  # Slate 50
BORDER_COL = colors.HexColor("#E2E8F0")


def _get_styles():
    ss = getSampleStyleSheet()
    title = ParagraphStyle(
        "ReportTitle",
        parent=ss["Heading1"],
        fontSize=20,
        leading=24,
        textColor=PRIMARY,
        spaceAfter=4,
    )
    subtitle = ParagraphStyle(
        "ReportSubtitle",
        parent=ss["Normal"],
        fontSize=10,
        leading=14,
        textColor=SECONDARY,
        spaceAfter=10,
    )
    section_h = ParagraphStyle(
        "SectionH",
        parent=ss["Heading2"],
        fontSize=13,
        leading=17,
        textColor=ACCENT,
        spaceBefore=10,
        spaceAfter=4,
    )
    body = ParagraphStyle(
        "ReportBody",
        parent=ss["Normal"],
        fontSize=9,
        leading=13,
        textColor=PRIMARY,
    )
    bullet = ParagraphStyle(
        "ReportBullet",
        parent=body,
        leftIndent=12,
        spaceAfter=2,
    )
    table_cell = ParagraphStyle(
        "TableCell",
        parent=ss["Normal"],
        fontSize=8.5,
        leading=11,
        textColor=PRIMARY,
    )
    table_cell_bold = ParagraphStyle(
        "TableCellBold",
        parent=table_cell,
        fontName="Helvetica-Bold",
    )
    return {
        "title": title,
        "subtitle": subtitle,
        "section": section_h,
        "body": body,
        "bullet": bullet,
        "cell": table_cell,
        "cell_bold": table_cell_bold,
    }


def _esc(val: object) -> str:
    """Safely XML-escape dynamic text for ReportLab Paragraphs to prevent tag injection or malformed XML crashes."""
    if val is None:
        return ""
    return saxutils.escape(str(val))


def generate_candidate_pdf(
    candidate_name: str,
    job_title: str,
    match_result: MatchResult,
    keyword_analysis: Optional[KeywordAnalysis] = None,
) -> bytes:
    """Generate professional PDF evaluation report for a candidate match."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    s = _get_styles()
    story = []

    # Title & Header
    story.append(Paragraph("ResumeIQ — Candidate Match Evaluation", s["title"]))
    story.append(Paragraph(f"<b>Candidate:</b> {_esc(candidate_name)} &nbsp;|&nbsp; <b>Target Role:</b> {_esc(job_title)}", s["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1, color=ACCENT, spaceAfter=8))

    # Overall Score Box
    verdict_color = (
        SUCCESS if match_result.overall_score >= 80
        else (ACCENT if match_result.overall_score >= 65
        else (WARNING if match_result.overall_score >= 45 else DANGER))
    )
    score_data = [
        [
            Paragraph(f"<b>Overall Compatibility Score</b>", s["cell_bold"]),
            Paragraph(f"<b>Verdict Band</b>", s["cell_bold"]),
        ],
        [
            Paragraph(f"<font size=16 color='{verdict_color.hexval()}'><b>{match_result.overall_score}%</b></font>", s["cell"]),
            Paragraph(f"<font size=14 color='{verdict_color.hexval()}'><b>{match_result.verdict.value} Fit</b></font>", s["cell"]),
        ],
    ]
    score_table = Table(score_data, colWidths=[270, 270])
    score_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), LIGHT_BG),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COL),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER_COL),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
    ]))
    story.append(score_table)
    story.append(Spacer(1, 10))

    # Component Scores Table
    story.append(Paragraph("Compatibility Breakdown", s["section"]))
    comp_rows = [
        [
            Paragraph("Component", s["cell_bold"]),
            Paragraph("Weight", s["cell_bold"]),
            Paragraph("Score", s["cell_bold"]),
            Paragraph("Weighted", s["cell_bold"]),
            Paragraph("Details", s["cell_bold"]),
        ]
    ]
    for c in match_result.component_scores:
        comp_rows.append([
            Paragraph(_esc(c.name), s["cell"]),
            Paragraph(f"{int(c.weight * 100)}%", s["cell"]),
            Paragraph(f"{c.score:.1f}%", s["cell"]),
            Paragraph(f"{c.weighted_score:.1f}%", s["cell"]),
            Paragraph(_esc(c.details), s["cell"]),
        ])
    comp_table = Table(comp_rows, colWidths=[120, 45, 45, 55, 275])
    comp_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT_BG),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COL),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER_COL),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(comp_table)
    story.append(Spacer(1, 10))

    # Strengths
    if match_result.strengths:
        story.append(Paragraph("Key Strengths & Evidence", s["section"]))
        for strength in match_result.strengths:
            story.append(Paragraph(f"• {_esc(strength)}", s["bullet"]))
        story.append(Spacer(1, 6))

    # Weaknesses
    if match_result.weaknesses:
        story.append(Paragraph("Identified Gaps & Weaknesses", s["section"]))
        for weakness in match_result.weaknesses:
            story.append(Paragraph(f"• {_esc(weakness)}", s["bullet"]))
        story.append(Spacer(1, 6))

    # Skill Gap Table
    story.append(Paragraph("Skills Alignment Overview", s["section"]))
    matched_str = _esc(", ".join(match_result.matched_skills[:8])) or "None"
    missing_req_str = _esc(", ".join(match_result.missing_required_skills[:6])) or "None (Full required coverage!)"
    missing_pref_str = _esc(", ".join(match_result.missing_preferred_skills[:6])) or "None"

    skills_data = [
        [Paragraph("<b>Status</b>", s["cell_bold"]), Paragraph("<b>Skills</b>", s["cell_bold"])],
        [Paragraph("<font color='#16A34A'><b>Matched Skills</b></font>", s["cell"]), Paragraph(matched_str, s["cell"])],
        [Paragraph("<font color='#DC2626'><b>Missing Required</b></font>", s["cell"]), Paragraph(missing_req_str, s["cell"])],
        [Paragraph("<font color='#D97706'><b>Missing Preferred</b></font>", s["cell"]), Paragraph(missing_pref_str, s["cell"])],
    ]
    skills_table = Table(skills_data, colWidths=[130, 410])
    skills_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT_BG),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COL),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER_COL),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(skills_table)
    story.append(Spacer(1, 10))

    # Recommendations
    if match_result.recommendations:
        story.append(Paragraph("Actionable Recommendations", s["section"]))
        for rec in match_result.recommendations:
            story.append(Paragraph(f"• {_esc(rec)}", s["bullet"]))
        story.append(Spacer(1, 6))

    # ATS Keywords
    if keyword_analysis:
        story.append(Paragraph("ATS Keyword Optimization", s["section"]))
        story.append(Paragraph(f"<b>ATS Match Rate:</b> {keyword_analysis.ats_match_percentage}%", s["body"]))
        if keyword_analysis.missing_keywords:
            missing_terms = [_esc(k.keyword) for k in keyword_analysis.missing_keywords[:6]]
            story.append(Paragraph(f"<b>Key Missing Terms:</b> {', '.join(missing_terms)}", s["body"]))

    doc.build(story)
    return buffer.getvalue()


def generate_recruiter_summary_pdf(
    job_title: str,
    ranking_result: RankingResult,
) -> bytes:
    """Generate PDF summary report for recruiter multi-candidate ranking."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=36,
    )
    s = _get_styles()
    story = []

    # Title
    story.append(Paragraph("ResumeIQ — Recruiter Candidate Ranking Report", s["title"]))
    story.append(Paragraph(f"<b>Target Role:</b> {_esc(job_title)} &nbsp;|&nbsp; <b>Total Evaluated:</b> {ranking_result.total_processed} Candidates", s["subtitle"]))
    story.append(HRFlowable(width="100%", thickness=1, color=ACCENT, spaceAfter=8))

    # Ranked Table
    story.append(Paragraph("Candidate Leaderboard", s["section"]))
    table_rows = [
        [
            Paragraph("Rank", s["cell_bold"]),
            Paragraph("Candidate", s["cell_bold"]),
            Paragraph("Score", s["cell_bold"]),
            Paragraph("Verdict", s["cell_bold"]),
            Paragraph("Assessment & Key Reason", s["cell_bold"]),
        ]
    ]

    for cand in ranking_result.candidates:
        cname = _esc(cand.candidate_name or cand.filename)
        verdict_str = _esc(cand.verdict.value if cand.error is None else "Error")
        reason_str = _esc(cand.one_line_reason or cand.error or "Evaluated")

        table_rows.append([
            Paragraph(f"#{cand.rank}", s["cell_bold"]),
            Paragraph(cname, s["cell"]),
            Paragraph(f"{cand.overall_score:.1f}%", s["cell"]),
            Paragraph(verdict_str, s["cell"]),
            Paragraph(reason_str, s["cell"]),
        ])

    ranked_table = Table(table_rows, colWidths=[35, 120, 50, 60, 275])
    ranked_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT_BG),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_COL),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, BORDER_COL),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(ranked_table)
    story.append(Spacer(1, 12))

    # Top 3 Candidates Deep Dive
    story.append(Paragraph("Top Candidates Spotlight", s["section"]))
    for i, top_c in enumerate(ranking_result.top_candidates, 1):
        cname = _esc(top_c.candidate_name or top_c.filename)
        matched_str = _esc(", ".join(top_c.match_result.matched_skills[:5])) if top_c.match_result else "N/A"
        top_reason = _esc(top_c.one_line_reason or "")
        story.append(Paragraph(
            f"<b>#{i} {cname} ({top_c.overall_score}% — {top_c.verdict.value}):</b> {top_reason}<br/>"
            f"<font color='#555555'>Core Matches: {matched_str}</font>",
            s["bullet"]
        ))
        story.append(Spacer(1, 3))

    doc.build(story)
    return buffer.getvalue()
