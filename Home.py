"""ResumeIQ — AI-Powered Resume Analyzer & Job Matching System.
Streamlit Landing Page.
"""

import os
import requests
import streamlit as st

try:
    from ui_helpers import (
        ensure_backend_running,
        enforce_auth,
        inject_responsive_css,
        render_sidebar_privacy_controls,
    )
except ImportError:
    from ui.ui_helpers import (
        ensure_backend_running,
        enforce_auth,
        inject_responsive_css,
        render_sidebar_privacy_controls,
    )

API_URL = os.getenv("RESUMEIQ_API_URL", "http://127.0.0.1:8000")

st.set_page_config(
    page_title="ResumeIQ — AI Resume & Job Matching",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 1. Dual-Platform Subprocess Fallback (Streamlit Cloud auto-start)
ensure_backend_running()

# 2. Access Password Gate (if APP_ACCESS_PASSWORD is set)
enforce_auth()

# 3. Responsive fluid CSS (clamp typography, touch targets, theme neutrality)
inject_responsive_css()

# 4. Privacy & Data Deletion Controls in Sidebar
render_sidebar_privacy_controls()

st.markdown('<div class="main-header">🎯 ResumeIQ</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">AI-Powered Resume Analyzer, Skill Normalization & Transparent Job Matching System</div>', unsafe_allow_html=True)

# System Status Check
backend_online = False
gemini_available = False
embedding_loaded = False

try:
    resp = requests.get(f"{API_URL}/health", timeout=2)
    if resp.status_code == 200:
        backend_online = True
        h_data = resp.json()
        gemini_available = h_data.get("gemini_available", False)
        embedding_loaded = h_data.get("embedding_model_loaded", False)
except Exception:
    pass

status_cols = st.columns(4)
with status_cols[0]:
    b_class = "badge-online" if backend_online else "badge-offline"
    b_text = "Backend: Online (Port 8000)" if backend_online else "Backend: Offline"
    st.markdown(f'<span class="badge-pill {b_class}">● {b_text}</span>', unsafe_allow_html=True)
with status_cols[1]:
    g_class = "badge-online" if gemini_available else "badge-pill"
    g_text = "Gemini LLM: Active" if gemini_available else "Gemini LLM: Rule-Based Fallback"
    st.markdown(f'<span class="badge-pill {g_class}">🤖 {g_text}</span>', unsafe_allow_html=True)
with status_cols[2]:
    e_class = "badge-online" if embedding_loaded else "badge-pill"
    e_text = "Embeddings: MiniLM Neural" if embedding_loaded else "Embeddings: TF-IDF Engine"
    st.markdown(f'<span class="badge-pill {e_class}">📐 {e_text}</span>', unsafe_allow_html=True)
with status_cols[3]:
    st.markdown('<span class="badge-pill badge-online">📚 Taxonomy: 501 Skills</span>', unsafe_allow_html=True)

st.markdown("<br/>", unsafe_allow_html=True)

col1, col2 = st.columns(2)

with col1:
    st.markdown("""
    <div class="feature-card">
        <h3>👤 Candidate Analyzer</h3>
        <p>Upload your resume (PDF or DOCX) to receive an instant, multi-dimensional assessment:</p>
        <ul>
            <li><b>Quality Score (0-100)</b>: Completeness, Impact & Metrics, Skills Diversity, Clarity, ATS-friendliness, Links</li>
            <li><b>500+ Skills Normalization</b>: Exact, alias ("js" → JavaScript, "k8s" → Kubernetes), and fuzzy matching</li>
            <li><b>Actionable Rewrites</b>: Weak bullet detection with Google X-Y-Z formula rewrites</li>
            <li><b>Role & Gap Detection</b>: Inferred role and missing expected skills</li>
            <li><b>Job Matcher</b>: Paste any JD to test compatibility and generate candidate PDF reports</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)
    if st.button("🚀 Open Candidate Analyzer", use_container_width=True, type="primary"):
        st.switch_page("pages/1_Candidate_Analyzer.py")

with col2:
    st.markdown("""
    <div class="feature-card">
        <h3>🏢 Recruiter Dashboard</h3>
        <p>Batch evaluate 2 to 50 resumes against a specific job description in parallel:</p>
        <ul>
            <li><b>Multi-Resume Ranking</b>: Concurrent evaluation via ThreadPoolExecutor with per-file error isolation</li>
            <li><b>Side-by-Side Matrix</b>: Candidates × Required Skills comparison matrix</li>
            <li><b>Explainable Scoring</b>: 40% Required Skills, 20% Semantic Cosine, 20% Experience, 10% Preferred, 10% Education</li>
            <li><b>Recruiter Filters</b>: Filter by minimum score, must-have skills, and years of experience</li>
            <li><b>Executive Summary PDF</b>: Export full leaderboard with candidate spotlights</li>
        </ul>
    </div>
    """, unsafe_allow_html=True)
    if st.button("📊 Open Recruiter Dashboard", use_container_width=True):
        st.switch_page("pages/2_Recruiter_Dashboard.py")

st.markdown("---")
st.markdown("""
### 🧠 How ResumeIQ Evaluates Resumes
- **Deterministic & Explainable**: No opaque numbers or hallucinated scores from LLMs. All scores derive from mathematical formulas and verified skill occurrences.
- **Local-First & Offline Capable**: Built with robust rule-based fallbacks and local TF-IDF / sentence-transformers embeddings.
- **Privacy First**: Resumes are processed locally in your workspace SQLite database. No data is stored externally.
""")
