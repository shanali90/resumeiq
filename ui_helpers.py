"""Shared UI helpers for ResumeIQ — auth gating, subprocess bootstrap, responsive styling, and privacy controls."""

from __future__ import annotations

import html
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Optional

import requests
import streamlit as st

from app.security import check_password_auth

API_URL = os.getenv("RESUMEIQ_API_URL", "http://127.0.0.1:8000")


def safe_text(val: object) -> str:
    """Safely escape text for HTML display to prevent XSS."""
    if val is None:
        return ""
    return html.escape(str(val))


def sync_secrets_to_env() -> None:
    """Synchronize Streamlit secrets to os.environ so child processes inherit them."""
    try:
        if hasattr(st, "secrets"):
            keys = [
                "GEMINI_API_KEY",
                "GEMINI_MODEL",
                "GEMINI_DAILY_LIMIT",
                "APP_ACCESS_PASSWORD",
                "DATA_ENCRYPTION_KEY",
                "APP_ENV",
                "API_HOST",
                "API_PORT",
            ]
            for key in keys:
                if key not in os.environ and key in st.secrets:
                    val = str(st.secrets[key]).strip()
                    if val:
                        os.environ[key] = val
                elif key not in os.environ and key.lower() in st.secrets:
                    val = str(st.secrets[key.lower()]).strip()
                    if val:
                        os.environ[key] = val
    except Exception:
        pass


@st.cache_resource(show_spinner=False)
def ensure_backend_running() -> bool:
    """Dual-Platform Fallback for Streamlit Community Cloud without Docker.

    Checks if FastAPI backend is responding on 127.0.0.1:8000.
    If not, spawns uvicorn in a background subprocess and waits up to 5 seconds.
    """
    # 1. Sync secrets to environment first
    sync_secrets_to_env()

    # 2. Check if backend is already responding
    try:
        resp = requests.get(f"{API_URL}/health", timeout=1.5)
        if resp.status_code == 200:
            return True
    except Exception:
        pass

    # 3. Attempt to launch uvicorn as subprocess
    try:
        # Determine working directory containing 'app'
        candidate_dirs = [
            os.path.dirname(os.path.abspath(__file__)),
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            os.path.abspath(os.getcwd()),
        ]
        target_dir = None
        for d in candidate_dirs:
            if os.path.isdir(os.path.join(d, "app")):
                target_dir = d
                break
        if not target_dir:
            target_dir = os.path.abspath(os.getcwd())

        env_copy = os.environ.copy()
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
                "--workers",
                "1",
                "--no-access-log",
            ],
            cwd=target_dir,
            env=env_copy,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Retry loop: poll /health for up to 5 seconds
        for _ in range(12):
            time.sleep(0.5)
            try:
                r = requests.get(f"{API_URL}/health", timeout=1.0)
                if r.status_code == 200:
                    return True
            except Exception:
                continue
    except Exception as exc:
        st.sidebar.warning(f"Backend auto-start notice: {exc}")

    return False


def get_configured_password() -> Optional[str]:
    """Retrieve access password from environment variable or Streamlit secrets."""
    # 1. Environment variable
    pwd = os.getenv("APP_ACCESS_PASSWORD")
    if pwd:
        return pwd.strip()

    # 2. st.secrets fallback (Streamlit Community Cloud)
    try:
        if hasattr(st, "secrets"):
            if "APP_ACCESS_PASSWORD" in st.secrets:
                return str(st.secrets["APP_ACCESS_PASSWORD"]).strip()
            if "app_access_password" in st.secrets:
                return str(st.secrets["app_access_password"]).strip()
    except Exception:
        pass

    return None


def enforce_auth() -> None:
    """Enforce optional access control password with brute-force lockout."""
    correct_password = get_configured_password()
    if not correct_password:
        return  # No password configured, open demo access

    if st.session_state.get("authenticated", False):
        return  # Already authenticated in this session

    # Render Password Gate
    st.markdown("""
    <div style="max-width: 440px; margin: 40px auto; padding: 24px; border: 1px solid rgba(148, 163, 184, 0.25); border-radius: 12px; background: rgba(30, 41, 59, 0.4);">
        <h2 style="margin-top:0;">🔒 ResumeIQ Access Required</h2>
        <p style="color: #94A3B8; font-size: 0.95rem;">This instance is protected by an access password. Please enter the password configured in your environment secrets to proceed.</p>
    </div>
    """, unsafe_allow_html=True)

    with st.form("auth_form", clear_on_submit=False):
        pwd_input = st.text_input("Access Password", type="password", placeholder="Enter access password")
        submitted = st.form_submit_button("Unlock ResumeIQ", use_container_width=True, type="primary")

        if submitted:
            client_ip = "session_user"
            is_valid, msg = check_password_auth(pwd_input, correct_password, client_ip=client_ip)
            if is_valid:
                st.session_state["authenticated"] = True
                st.success("Access granted!")
                st.rerun()
            else:
                st.error(msg)

    st.stop()


def inject_responsive_css() -> None:
    """Inject fluid responsive CSS with clamp(), touch target optimization, and theme neutrality."""
    st.markdown("""
    <style>
        /* Responsive fluid typography */
        .main-header {
            font-size: clamp(1.8rem, 4.5vw, 2.7rem) !important;
            font-weight: 700;
            background: linear-gradient(120deg, #0284C7, #38BDF8, #818CF8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 0.3rem;
            line-height: 1.2;
        }
        .sub-header {
            font-size: clamp(0.95rem, 2.2vw, 1.18rem) !important;
            opacity: 0.85;
            margin-bottom: 1.5rem;
            line-height: 1.4;
        }

        /* Touch-friendly buttons (min 44px height for mobile compliance) */
        button, .stButton > button, div[data-testid="stFormSubmitButton"] > button {
            min-height: 44px !important;
            font-size: clamp(0.9rem, 2vw, 1.0rem) !important;
            border-radius: 8px !important;
            padding: 8px 16px !important;
            touch-action: manipulation;
        }

        /* Responsive feature cards */
        .feature-card {
            background-color: rgba(30, 41, 59, 0.45);
            border: 1px solid rgba(148, 163, 184, 0.22);
            border-radius: 12px;
            padding: clamp(14px, 3vw, 24px);
            margin-bottom: 16px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }

        /* Horizontal scroll wrapper for data tables on mobile */
        div[data-testid="stTable"], div[data-testid="stDataFrame"], .dataframe-container {
            overflow-x: auto !important;
            -webkit-overflow-scrolling: touch;
            max-width: 100%;
        }

        /* Badges */
        .badge-pill {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: clamp(0.72rem, 1.8vw, 0.82rem);
            font-weight: 600;
            margin: 3px;
        }
        .badge-online { background-color: rgba(22, 163, 74, 0.2); color: #4ADE80; border: 1px solid #16A34A; }
        .badge-offline { background-color: rgba(220, 38, 38, 0.2); color: #F87171; border: 1px solid #DC2626; }

        /* Media queries for narrow viewports (360px - 480px) */
        @media (max-width: 480px) {
            .block-container {
                padding-top: 1rem !important;
                padding-left: 0.6rem !important;
                padding-right: 0.6rem !important;
            }
            .feature-card {
                padding: 12px !important;
            }
        }
    </style>
    """, unsafe_allow_html=True)


def render_sidebar_privacy_controls() -> None:
    """Render Privacy controls and 'Delete My Data' button in the sidebar."""
    with st.sidebar:
        st.markdown("---")
        st.markdown("### 🔒 Privacy & Data")
        st.caption("Data is stored in-memory/ephemeral SQLite and automatically purged after 24 hours.")
        if st.button("🗑️ Delete All My Data", use_container_width=True):
            try:
                resp = requests.delete(f"{API_URL}/resumes", timeout=3)
                if resp.status_code == 200:
                    st.success("All stored resumes and matches permanently deleted.")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.warning("Could not reach backend to purge data.")
            except Exception as exc:
                st.error(f"Error purging data: {exc}")


def get_sample_data_dir() -> Path:
    """Find sample data directory across various deployment layouts."""
    candidates = [
        Path(__file__).resolve().parent / "sample_data",
        Path(__file__).resolve().parent / "app" / "data" / "sample_data",
        Path(__file__).resolve().parent.parent / "tests" / "sample_data",
        Path(__file__).resolve().parent / "tests" / "sample_data",
    ]
    for p in candidates:
        if p.exists() and p.is_dir():
            return p
    return candidates[0]


SAMPLE_DATA_DIR = get_sample_data_dir()

EMBEDDED_SAMPLE_JDS: dict[str, str] = {
    "Senior ML Engineer": """Senior Machine Learning Engineer

Company: TechCorp AI
Location: San Francisco, CA (Hybrid)
Experience: 5+ years

About the Role:
We are looking for a Senior Machine Learning Engineer to join our AI team and drive the development of cutting-edge ML solutions.

Required Skills:
- Python (must have)
- PyTorch or TensorFlow (required)
- Experience with NLP and/or Computer Vision
- Strong understanding of deep learning architectures
- Experience deploying ML models to production
- Docker and Kubernetes
- SQL and data pipeline experience
- Git version control

Preferred Skills:
- Experience with LLMs and prompt engineering
- Knowledge of MLOps tools (MLflow, Weights & Biases)
- Cloud platform experience (AWS, GCP, or Azure)
- Published research or patents (nice to have)
- Experience with distributed training

Education:
MS or PhD in Computer Science, Mathematics, or related field preferred

Responsibilities:
- Design and implement ML models for production systems
- Collaborate with cross-functional teams to define ML solutions
- Optimize model performance and reduce inference latency
- Mentor junior engineers
- Contribute to ML infrastructure and tooling
""",
    "Full Stack Developer": """Full Stack Developer

Company: WebCo
Location: Remote
Experience: 3+ years

About the Role:
Join our engineering team to build modern web applications used by thousands of users daily.

Required Skills:
- JavaScript/TypeScript (must have)
- React or Vue.js (required)
- Node.js (required)
- PostgreSQL or MySQL
- REST API design
- Git

Preferred Skills:
- Next.js or Nuxt.js (nice to have)
- GraphQL (plus)
- Docker
- Cloud deployment (AWS, Vercel, or similar)
- CI/CD pipelines
- Testing frameworks (Jest, Cypress)

Education:
Bachelor's degree in Computer Science or equivalent experience

Responsibilities:
- Develop responsive, accessible web applications
- Design and implement RESTful APIs
- Write unit and integration tests
- Participate in code reviews
- Collaborate with designers and product managers
""",
}


def load_sample_jd(choice: str) -> str:
    """Safely return sample job description text by name with disk lookup and embedded fallback."""
    if not choice or choice == "None":
        return ""
    if choice in EMBEDDED_SAMPLE_JDS:
        target_fn = "jd_ml_engineer.txt" if choice == "Senior ML Engineer" else "jd_fullstack_dev.txt"
        file_path = SAMPLE_DATA_DIR / target_fn
        if file_path.exists():
            try:
                return file_path.read_text(encoding="utf-8")
            except Exception:
                pass
        return EMBEDDED_SAMPLE_JDS[choice]
    return ""

