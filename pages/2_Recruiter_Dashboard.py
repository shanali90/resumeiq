"""Recruiter Dashboard — Batch multi-resume ranking, comparison matrix, and hiring reasons."""

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
        SAMPLE_DATA_DIR,
        load_sample_jd,
    )
except ImportError:
    from ui.ui_helpers import (
        ensure_backend_running,
        enforce_auth,
        inject_responsive_css,
        render_sidebar_privacy_controls,
        safe_text,
        SAMPLE_DATA_DIR,
        load_sample_jd,
    )

API_URL = os.getenv("RESUMEIQ_API_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="Recruiter Dashboard — ResumeIQ", page_icon="🏢", layout="wide")

# 1. Ensure backend process & check auth
ensure_backend_running()
enforce_auth()
inject_responsive_css()
render_sidebar_privacy_controls()

st.markdown("""
<style>
    .candidate-card {
        background-color: rgba(30, 41, 59, 0.6);
        border: 1px solid rgba(148, 163, 184, 0.2);
        border-radius: 8px;
        padding: 14px 18px;
        margin-bottom: 10px;
    }
    .rank-num {
        font-size: 1.6rem;
        font-weight: 800;
        color: #0284C7;
    }
</style>
""", unsafe_allow_html=True)

st.title("🏢 Recruiter Ranking Dashboard")
st.caption("Upload a job description and batch evaluate up to 50 resumes simultaneously.")

# 1. Job Description Input
col_jd_text, col_jd_sample = st.columns([3, 1])

with col_jd_sample:
    st.markdown("**Sample Job:**")
    jd_choice = st.selectbox("Select JD:", ["None", "Senior ML Engineer", "Full Stack Developer"])
    sample_jd_content = load_sample_jd(jd_choice)

with col_jd_text:
    jd_text_input = st.text_area("Job Description", value=sample_jd_content, height=140, placeholder="Paste job description requirements...")

# 2. Resumes Upload
st.markdown("### 📁 Candidate Resumes")
col_files, col_sample_batch = st.columns([3, 2])

with col_files:
    uploaded_files = st.file_uploader(
        "Upload Resumes (PDF & DOCX, 2-50 files)",
        type=["pdf", "docx"],
        accept_multiple_files=True,
    )

with col_sample_batch:
    st.markdown("**Or one-click test with sample pool:**")
    use_sample_pool = st.checkbox("Include 5 sample resumes (Sarah Chen, Alex Rivera, Priya Patel, John Smith, Michael Brown)", value=False)

# Filters Bar
st.markdown("### ⚙️ Recruiter Filters")
f_col1, f_col2, f_col3 = st.columns(3)
with f_col1:
    min_score_filter = st.slider("Minimum Match Score (%)", min_value=0, max_value=100, value=0, step=5)
with f_col2:
    must_have_input = st.text_input("Must-Have Skills (comma-separated)", placeholder="e.g. Python, Docker")
with f_col3:
    min_exp_filter = st.number_input("Minimum Experience (Years)", min_value=0, max_value=15, value=0)

# Process Button
all_files_to_send: list[tuple[str, bytes, str]] = []

if uploaded_files:
    for f in uploaded_files:
        all_files_to_send.append((f.name, f.getvalue(), f.type))

if use_sample_pool:
    samples = ["strong_ml_engineer.pdf", "web_developer.pdf", "fresher.docx", "weak_resume.pdf", "career_changer.docx"]
    loaded_count = 0
    for s_name in samples:
        s_path = SAMPLE_DATA_DIR / s_name
        if s_path.exists():
            ctype = "application/pdf" if s_name.endswith(".pdf") else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            all_files_to_send.append((s_name, s_path.read_bytes(), ctype))
            loaded_count += 1
    if loaded_count == 0:
        st.warning("Sample resume files not found on disk. Please upload candidate resumes above.")

st.write(f"Total resumes queued for ranking: **{len(all_files_to_send)}**")

if st.button("🚀 Run Batch Ranking", type="primary", disabled=len(all_files_to_send) < 1 or not jd_text_input.strip()):
    with st.spinner(f"Evaluating {len(all_files_to_send)} resumes concurrently with ThreadPoolExecutor..."):
        try:
            # Build multipart form data
            files_payload = [
                ("files", (fname, fbytes, ctype))
                for fname, fbytes, ctype in all_files_to_send
            ]
            data_payload = {
                "job_text": jd_text_input,
                "min_score": min_score_filter if min_score_filter > 0 else "",
                "must_have_skills": must_have_input if must_have_input else "",
                "min_experience_years": min_exp_filter if min_exp_filter > 0 else "",
            }

            resp = requests.post(f"{API_URL}/rank", data=data_payload, files=files_payload, timeout=60)
            if resp.status_code == 200:
                st.session_state["ranking_data"] = resp.json()
                st.success("Batch ranking completed successfully!")
            else:
                st.error(f"Ranking failed: {resp.text}")
        except Exception as exc:
            st.error(f"Backend connection error: {exc}")

# Display Ranking Results
if "ranking_data" in st.session_state:
    r_data = st.session_state["ranking_data"]
    candidates = r_data.get("candidates", [])
    matrix = r_data.get("comparison_matrix", [])
    top_candidates = r_data.get("top_candidates", [])

    st.markdown("---")
    st.subheader(f"🏆 Candidate Leaderboard: {r_data.get('job_title', 'Target Role')}")
    st.caption(f"Processed {r_data.get('total_processed', 0)} candidates ({r_data.get('total_errors', 0)} errors isolated).")

    # Top 3 Spotlight
    if top_candidates:
        st.markdown("#### 🌟 Top 3 Recommendations")
        t_cols = st.columns(min(3, len(top_candidates)))
        for i, top_c in enumerate(top_candidates[:3]):
            with t_cols[i]:
                st.markdown(f"""
                <div class="candidate-card">
                    <span class="rank-num">#{i+1}</span> <b>{top_c.get('candidate_name') or top_c.get('filename')}</b><br/>
                    <b>Score:</b> {top_c.get('overall_score')}% ({top_c.get('verdict')})<br/>
                    <small><i>{top_c.get('one_line_reason')}</i></small>
                </div>
                """, unsafe_allow_html=True)

    # Leaderboard Table
    st.markdown("#### 📋 Full Ranked Results")
    for cand in candidates:
        with st.expander(f"#{cand.get('rank')} — {cand.get('candidate_name') or cand.get('filename')} ({cand.get('overall_score')}% • {cand.get('verdict')})", expanded=cand.get("rank") == 1):
            c_cols = st.columns([1, 2, 2])
            with c_cols[0]:
                st.metric("Overall Match", f"{cand.get('overall_score')}%")
                if cand.get("quality_score"):
                    st.metric("Resume Quality", f"{cand.get('quality_score')}/100")
            with c_cols[1]:
                st.write(f"**Assessment:** {cand.get('one_line_reason')}")
                if cand.get("error"):
                    st.error(f"Error note: {cand.get('error')}")
                mr = cand.get("match_result", {})
                if mr.get("matched_skills"):
                    st.write(f"**Matched Skills ({len(mr['matched_skills'])}):** {', '.join(mr['matched_skills'][:8])}")
            with c_cols[2]:
                if mr.get("missing_required_skills"):
                    st.write(f"**Missing Required Skills:** {', '.join(mr['missing_required_skills'])}")
                if mr.get("strengths"):
                    st.write(f"**Strengths:** {mr['strengths'][0]}")

    # Comparison Matrix
    if matrix:
        st.markdown("### 🧩 Required Skills Comparison Matrix")
        # Flatten matrix into rows
        header_skills = [cell["skill"] for cell in matrix[0]] if matrix and matrix[0] else []
        if header_skills:
            matrix_display = []
            for row in matrix:
                cname = row[0]["candidate"] if row else "Unknown"
                row_dict = {"Candidate": cname}
                for cell in row:
                    row_dict[cell["skill"]] = "✅ Yes" if cell["has_skill"] else "❌ No"
                matrix_display.append(row_dict)
            st.dataframe(matrix_display, use_container_width=True)
