"""Candidate Analyzer Page — Deep resume quality assessment, skills normalization, and JD matching."""

import os
from pathlib import Path
import requests
import streamlit as st

try:
    from ui_helpers import (
        ensure_backend_running,
        enforce_auth,
        inject_responsive_css,
        render_sidebar_privacy_controls,
        safe_text,
    )
except ImportError:
    from ui.ui_helpers import (
        ensure_backend_running,
        enforce_auth,
        inject_responsive_css,
        render_sidebar_privacy_controls,
        safe_text,
    )

API_URL = os.getenv("RESUMEIQ_API_URL", "http://127.0.0.1:8000")
SAMPLE_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "tests" / "sample_data"

st.set_page_config(page_title="Candidate Analyzer — ResumeIQ", page_icon="👤", layout="wide")

# 1. Ensure backend process & check auth
ensure_backend_running()
enforce_auth()
inject_responsive_css()
render_sidebar_privacy_controls()

st.markdown("""
<style>
    .score-badge {
        font-size: 2.2rem;
        font-weight: 800;
        padding: 10px 20px;
        border-radius: 12px;
        display: inline-block;
        margin-bottom: 10px;
    }
    .score-green { background: rgba(22, 163, 74, 0.15); color: #4ADE80; border: 1px solid #16A34A; }
    .score-blue { background: rgba(2, 132, 199, 0.15); color: #38BDF8; border: 1px solid #0284C7; }
    .score-amber { background: rgba(217, 119, 6, 0.15); color: #FBBF24; border: 1px solid #D97706; }
    .score-red { background: rgba(220, 38, 38, 0.15); color: #F87171; border: 1px solid #DC2626; }
    .chip {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 16px;
        font-size: 0.82rem;
        font-weight: 500;
        margin: 3px;
    }
    .chip-tech { background-color: rgba(2, 132, 199, 0.2); color: #38BDF8; border: 1px solid rgba(2, 132, 199, 0.4); }
    .chip-soft { background-color: rgba(147, 51, 234, 0.2); color: #C084FC; border: 1px solid rgba(147, 51, 234, 0.4); }
    .chip-missing { background-color: rgba(239, 68, 68, 0.15); color: #F87171; border: 1px dashed #EF4444; }
    .suggestion-box {
        background-color: rgba(30, 41, 59, 0.5);
        border-left: 4px solid #0284C7;
        border-radius: 4px 8px 8px 4px;
        padding: 12px 16px;
        margin-bottom: 12px;
    }
    .sev-high { border-left-color: #EF4444; }
    .sev-med { border-left-color: #F59E0B; }
    .sev-low { border-left-color: #10B981; }
</style>
""", unsafe_allow_html=True)

st.title("👤 Candidate Resume Analyzer")
st.caption("Upload a resume (PDF/DOCX) for quality analysis, skill normalization, and job compatibility.")

# Input area: Upload or load sample
col_upload, col_sample = st.columns([3, 2])

uploaded_file = None
file_bytes = None
file_name = None

with col_upload:
    uploaded = st.file_uploader("Upload Resume (PDF or DOCX, max 5 MB)", type=["pdf", "docx"])
    if uploaded:
        uploaded_file = uploaded
        file_bytes = uploaded.getvalue()
        file_name = uploaded.name

with col_sample:
    st.markdown("**Or load a sample resume:**")
    sample_choice = st.selectbox(
        "Choose test resume",
        ["Select a sample...", "Sarah Chen (Strong ML Engineer)", "Alex Rivera (Web Developer)", "Priya Patel (Fresher CS)", "John Smith (Weak Resume)", "Michael Brown (Career Changer)"],
        index=0
    )
    if sample_choice != "Select a sample...":
        filename_map = {
            "Sarah Chen (Strong ML Engineer)": "strong_ml_engineer.pdf",
            "Alex Rivera (Web Developer)": "web_developer.pdf",
            "Priya Patel (Fresher CS)": "fresher.docx",
            "John Smith (Weak Resume)": "weak_resume.pdf",
            "Michael Brown (Career Changer)": "career_changer.docx",
        }
        chosen_file = filename_map[sample_choice]
        sample_path = SAMPLE_DATA_DIR / chosen_file
        if sample_path.exists():
            file_bytes = sample_path.read_bytes()
            file_name = chosen_file
            st.success(f"Loaded sample: {chosen_file} ({len(file_bytes):,} bytes)")

if st.button("🔍 Analyze Resume", type="primary", disabled=file_bytes is None):
    with st.spinner("Parsing resume, extracting structured profile, and computing quality score..."):
        try:
            files = {"file": (file_name, file_bytes, "application/pdf" if file_name.endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
            resp = requests.post(f"{API_URL}/resumes/analyze", files=files, timeout=30)
            if resp.status_code == 201:
                st.session_state["resume_analysis"] = resp.json()
                st.session_state["resume_raw_bytes"] = file_bytes
                st.session_state["resume_filename"] = file_name
                st.success("Analysis complete!")
            else:
                err_detail = resp.json().get("detail", resp.text)
                st.error(f"Analysis failed: {err_detail}")
        except Exception as exc:
            st.error(f"Connection error to backend: {exc}. Ensure FastAPI backend is running on port 8000.")

# Display results
if "resume_analysis" in st.session_state:
    data = st.session_state["resume_analysis"]
    profile = data.get("profile", {})
    quality = data.get("quality", {})
    skills = data.get("skills", [])
    candidate = profile.get("candidate", {})

    st.markdown("---")

    # Header Profile Card
    head_col1, head_col2 = st.columns([3, 1])
    with head_col1:
        st.subheader(f"📄 {candidate.get('name') or file_name}")
        contact_items = []
        if candidate.get("email"): contact_items.append(f"📧 {candidate['email']}")
        if candidate.get("phone"): contact_items.append(f"📞 {candidate['phone']}")
        if candidate.get("location"): contact_items.append(f"📍 {candidate['location']}")
        st.write(" • ".join(contact_items) if contact_items else "No contact details detected")

        link_items = []
        if candidate.get("linkedin"): link_items.append(f"[LinkedIn]({candidate['linkedin']})")
        if candidate.get("github"): link_items.append(f"[GitHub]({candidate['github']})")
        if candidate.get("portfolio"): link_items.append(f"[Portfolio]({candidate['portfolio']})")
        if link_items:
            st.markdown("🌐 " + " | ".join(link_items))

        if profile.get("summary"):
            with st.expander("📝 Professional Summary", expanded=True):
                st.write(profile["summary"])

    with head_col2:
        q_score = quality.get("overall_score", 0.0)
        badge_cls = "score-green" if q_score >= 80 else ("score-blue" if q_score >= 65 else ("score-amber" if q_score >= 50 else "score-red"))
        st.markdown(f'<div class="score-badge {badge_cls}">{q_score}/100</div>', unsafe_allow_html=True)
        st.caption(f"Inferred Role: **{quality.get('inferred_role', 'General')}**")
        st.caption(f"Extraction Mode: **{profile.get('extraction_mode', 'rule_based').upper()}**")

    # Quality Breakdown
    st.markdown("### 📊 Quality Breakdown")
    comp_cols = st.columns(len(quality.get("components", [])))
    for i, comp in enumerate(quality.get("components", [])):
        with comp_cols[i]:
            st.metric(comp["name"], f"{comp['score']}/{int(comp['max_score'])}")
            st.progress(comp["score"] / comp["max_score"])
            st.caption(comp.get("details", ""))

    # Skills Section
    st.markdown("### 🤹 Normalized Skills Inventory")
    tech_skills = [s for s in skills if s.get("category") == "technical"]
    soft_skills = [s for s in skills if s.get("category") == "soft"]

    st.write(f"**Technical Skills ({len(tech_skills)}):**")
    t_chips = "".join([f'<span class="chip chip-tech">{s["normalized"]}</span>' for s in tech_skills])
    st.markdown(t_chips or "*None detected*", unsafe_allow_html=True)

    if soft_skills:
        st.write(f"**Soft & Leadership Skills ({len(soft_skills)}):**")
        s_chips = "".join([f'<span class="chip chip-soft">{s["normalized"]}</span>' for s in soft_skills])
        st.markdown(s_chips, unsafe_allow_html=True)

    # Missing Skills Recommendation
    missing_role_skills = quality.get("missing_skills_for_role", [])
    if missing_role_skills:
        st.write(f"**Recommended Skills for {quality.get('inferred_role', 'Your Role')} Gaps:**")
        m_chips = "".join([f'<span class="chip chip-missing">+ {s}</span>' for s in missing_role_skills])
        st.markdown(m_chips, unsafe_allow_html=True)

    # Improvement Suggestions
    st.markdown("### 💡 Actionable Improvement Suggestions")
    suggestions = quality.get("improvement_suggestions", [])
    if suggestions:
        for sugg in suggestions:
            sev = sugg.get("severity", "medium").lower()
            sev_class = f"sev-{sev}"
            sev_badge = "🔴 HIGH" if sev == "high" else ("🟡 MEDIUM" if sev == "medium" else "🟢 LOW")
            st.markdown(f"""
            <div class="suggestion-box {sev_class}">
                <b>{sev_badge} [{sugg.get('category')}]:</b> {sugg.get('issue')}<br/>
                <b>Fix:</b> {sugg.get('fix')}
                {f"<br/><b>Example:</b> <i>{sugg.get('rewritten_example')}</i>" if sugg.get('rewritten_example') else ""}
            </div>
            """, unsafe_allow_html=True)
    else:
        st.success("No critical issues found! Your resume adheres to strong ATS and impact guidelines.")

    # Timeline / Experience
    with st.expander("💼 Experience & Education History"):
        exps = profile.get("experience", [])
        if exps:
            st.markdown("#### Work Experience")
            for exp in exps:
                comp_str = f" at {exp['company']}" if exp.get("company") else ""
                date_str = f" ({exp.get('start', '')} - {exp.get('end', '')})"
                st.markdown(f"**{exp.get('title') or 'Role'}**{comp_str}{date_str}")
                for b in exp.get("bullets", []):
                    st.write(f"• {b}")
                st.write("")
        edus = profile.get("education", [])
        if edus:
            st.markdown("#### Education")
            for edu in edus:
                inst_str = f" — {edu['institution']}" if edu.get("institution") else ""
                date_str = f" ({edu.get('start', '')} - {edu.get('end', '')})"
                st.write(f"🎓 **{edu.get('degree') or 'Degree'}**{inst_str}{date_str}")

    # Match Against a Job Description Section
    st.markdown("---")
    st.markdown("### 🎯 Match With a Target Job Description")
    st.write("Check your compatibility score, missing required skills, and download an official candidate evaluation PDF report.")

    jd_sample_col, jd_text_col = st.columns([1, 2])
    with jd_sample_col:
        jd_sample = st.radio("Load Sample Job Description:", ["None", "Senior ML Engineer", "Full Stack Developer"])
        sample_jd_text = ""
        if jd_sample == "Senior ML Engineer":
            sample_jd_text = (SAMPLE_DATA_DIR / "jd_ml_engineer.txt").read_text(encoding="utf-8")
        elif jd_sample == "Full Stack Developer":
            sample_jd_text = (SAMPLE_DATA_DIR / "jd_fullstack_dev.txt").read_text(encoding="utf-8")

    with jd_text_col:
        jd_input = st.text_area("Job Description Text", value=sample_jd_text, height=180, placeholder="Paste a job description here...")

    if st.button("⚡ Test Job Compatibility", type="primary", disabled=not jd_input.strip()):
        with st.spinner("Analyzing job requirements and computing compatibility score..."):
            try:
                # 1. Create Job in backend
                j_resp = requests.post(f"{API_URL}/jobs", data={"text": jd_input}, timeout=20)
                if j_resp.status_code == 201:
                    job_data = j_resp.json()
                    job_id = job_data["id"]

                    # 2. Run match
                    m_resp = requests.post(f"{API_URL}/match", json={"resume_id": data["id"], "job_id": job_id}, timeout=20)
                    if m_resp.status_code == 200:
                        st.session_state["match_result"] = m_resp.json()
                        st.session_state["matched_job_id"] = job_id
                        st.session_state["matched_job_title"] = job_data["job_description"].get("title", "Target Role")
                        st.success("Compatibility calculated!")
                    else:
                        st.error(f"Matching failed: {m_resp.text}")
                else:
                    st.error(f"Job creation failed: {j_resp.text}")
            except Exception as exc:
                st.error(f"Error during matching: {exc}")

    # Show Match Result
    if "match_result" in st.session_state:
        mr = st.session_state["match_result"]
        st.markdown(f"#### Compatibility: **{mr['overall_score']}%** ({mr['verdict']})")
        st.progress(mr["overall_score"] / 100.0)

        m_cols = st.columns(len(mr.get("component_scores", [])))
        for i, cs in enumerate(mr.get("component_scores", [])):
            with m_cols[i]:
                st.metric(cs["name"], f"{cs['score']:.1f}%", f"{cs['weighted_score']:.1f} pts")
                st.caption(cs.get("details", ""))

        st.markdown("**Matched Skills:** " + ", ".join(mr.get("matched_skills", [])))
        if mr.get("missing_required_skills"):
            st.markdown("**Missing Required Skills:** " + ", ".join(mr.get("missing_required_skills", [])))

        # Download Report PDF
        try:
            # Fetch latest report id
            reports_resp = requests.get(f"{API_URL}/reports", timeout=5)
            if reports_resp.status_code == 200 and reports_resp.json():
                latest_report_id = reports_resp.json()[0]["id"]
                pdf_resp = requests.get(f"{API_URL}/reports/{latest_report_id}.pdf", timeout=10)
                if pdf_resp.status_code == 200:
                    st.download_button(
                        label="📥 Download Candidate Evaluation PDF Report",
                        data=pdf_resp.content,
                        file_name=f"resumeiq_evaluation_{data['id']}.pdf",
                        mime="application/pdf",
                    )
        except Exception:
            pass
