"""Reports & Privacy Management Page — View past analyses, download reports, and delete records."""

import os
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

st.set_page_config(page_title="Reports & Privacy — ResumeIQ", page_icon="📑", layout="wide")

# 1. Ensure backend process & check auth
ensure_backend_running()
enforce_auth()
inject_responsive_css()
render_sidebar_privacy_controls()

st.title("📑 Evaluation Reports & Privacy Management")
st.caption("Access historical resume analyses, export executive PDF/JSON reports, and manage local data.")

try:
    resp = requests.get(f"{API_URL}/reports", timeout=10)
    if resp.status_code == 200:
        reports = resp.json()
    else:
        reports = []
        st.warning("Could not retrieve reports from backend.")
except Exception as exc:
    reports = []
    st.error(f"Cannot connect to backend: {exc}")

if not reports:
    st.info("No evaluations found yet. Run an analysis in the Candidate Analyzer or Recruiter Dashboard!")
else:
    st.subheader(f"Stored Evaluations ({len(reports)})")

    for rep in reports:
        match_id = rep["id"]
        c_name = rep.get("candidate_name", "Candidate")
        j_title = rep.get("job_title", "Target Role")
        score = rep.get("overall_score", 0.0)
        verdict = rep.get("verdict", "N/A")
        date_str = rep.get("created_at", "")[:10]

        with st.container():
            col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])
            with col1:
                st.markdown(f"**{c_name}** → *{j_title}*")
                st.caption(f"Date: {date_str} • Match ID: #{match_id}")
            with col2:
                st.metric("Compatibility", f"{score}%", verdict)
            with col3:
                # PDF Download button
                pdf_url = f"{API_URL}/reports/{match_id}.pdf"
                try:
                    pdf_data = requests.get(pdf_url, timeout=5).content
                    st.download_button(
                        label="📄 PDF",
                        data=pdf_data,
                        file_name=f"report_{match_id}_{c_name.replace(' ', '_')}.pdf",
                        mime="application/pdf",
                        key=f"pdf_{match_id}",
                    )
                except Exception:
                    st.button("PDF", disabled=True, key=f"pdf_dis_{match_id}")
            with col4:
                # JSON Download button
                json_url = f"{API_URL}/reports/{match_id}.json"
                try:
                    json_data = requests.get(json_url, timeout=5).text
                    st.download_button(
                        label="💾 JSON",
                        data=json_data,
                        file_name=f"report_{match_id}.json",
                        mime="application/json",
                        key=f"json_{match_id}",
                    )
                except Exception:
                    st.button("JSON", disabled=True, key=f"json_dis_{match_id}")
            with col5:
                # Delete resume button (privacy compliance)
                resume_id = rep.get("resume_id")
                if st.button("🗑️ Delete", key=f"del_{match_id}"):
                    del_resp = requests.delete(f"{API_URL}/resumes/{resume_id}")
                    if del_resp.status_code == 200:
                        st.success("Deleted!")
                        st.rerun()
                    else:
                        st.error("Failed to delete.")
            st.divider()

st.markdown("---")
st.markdown("""
### 🔒 Data Privacy & Local Storage
- **Local SQLite Storage**: Resumes and analyses are stored strictly inside your local workspace database (`resumeiq.db`).
- **No Third-Party Transmission of Documents**: Raw resume files are never sent to external servers except for prompt text passed to Gemini when an API key is configured.
- **Right to Erasure**: Use the **Delete** button above at any time to permanently wipe a candidate's resume, text, and match evaluations from the database.
""")
