# ResumeIQ — AI-Powered Resume Analyzer & Job Matching System

[![Render](https://img.shields.io/badge/Render-Docker%20Web%20Service-46E3B7?logo=render&logoColor=white)](https://render.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-Community%20Cloud-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io)
[![Python](https://img.shields.io/badge/Python-3.12%20%7C%203.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![Security Audited](https://img.shields.io/badge/Security-Hardened%20%26%20Audited-10B981)](#security--privacy)

ResumeIQ is an explainable, intelligent resume evaluation and candidate-job matching platform built with FastAPI, Streamlit, and Google Gemini.

Designed for high reliability under strict memory constraints (< 512 MB RAM footprint) and dual-platform deployment:
1. **Primary Target**: [Render.com](https://render.com) Free Docker Web Service.
2. **Backup Target**: [Streamlit Community Cloud](https://share.streamlit.io).

---

## 🚀 Quick Deployment Guide

### Option A: Streamlit Community Cloud (Primary)
1. Fork or push this repository to GitHub.
2. Sign in to [share.streamlit.io](https://share.streamlit.io).
3. Click **New app** (or **Create app**), select repository `shanali90/resumeiq` and branch `main`.
4. Set **Main file path** to `Home.py`.
5. Under **Advanced settings**, select Python **3.12**.
6. In **Secrets**, paste:
   ```toml
   GEMINI_API_KEY = "your_key_here"
   GEMINI_MODEL = "gemini-2.5-flash"
   GEMINI_DAILY_LIMIT = "50"
   APP_ACCESS_PASSWORD = ""
   APP_ENV = "production"
   ```
7. Click **Deploy**. The app's built-in `@st.cache_resource` bootstrapper automatically spawns the internal FastAPI backend process without manual intervention.
8. *Note*: Inactive apps sleep after inactivity. Clicking "Yes, get this app back up!" can take up to about a minute to wake as services start.

---

### Option B: Render.com (Free Docker Web Service — Backup)
1. Sign in to [Render.com](https://dashboard.render.com).
2. Click **New +** > **Web Service** and select this repository.
3. Configure settings:
   - **Environment**: `Docker`
   - **Instance Type**: `Free (512 MB RAM)`
   - **Branch**: `main`
4. Under **Environment Variables**, add:
   - `GEMINI_API_KEY`: *(Your key or leave empty)*
   - `GEMINI_MODEL`: `gemini-2.5-flash`
   - `APP_ENV`: `production`
5. Click **Deploy Web Service**.
6. *(Optional)* Configure a free ping on [cron-job.org](https://cron-job.org) every 10 minutes to keep Render awake 24/7.

---

## 🔒 Security & Privacy Features

- **Field-Level At-Rest Encryption**: Contact details and raw text are encrypted via Fernet cryptography.
- **Privacy Compliance & Auto-Purge**: Stored data is ephemeral and automatically purged after 24 hours. A "Delete My Data" button provides one-click instant purging.
- **Strict File Upload Constraints**: Magic byte validation (`%PDF-`, `PK\x03\x04`), 5 MB file size limit, 10-page PDF cap, and DOCX zip-bomb prevention (entry count, decompression ratio, and traversal checks).
- **Prompt Injection Defense**: Resume and job description text is treated as strictly untrusted data. Scores are computed 100% deterministically by Python algorithms, preventing prompt injection attacks from manipulating scores.
- **XSS & PDF Tag Injection Neutralization**: All user strings are escaped with `html.escape()` in the web UI and `xml.sax.saxutils.escape()` in ReportLab PDF generation.
- **Budget Guard**: Configurable daily Gemini API call limit with automatic fallback to local rule-based mode.

---

## 📁 Repository Layout

```
.
├── Dockerfile              # Production python:3.12-slim image (non-root UID 1000)
├── start.sh                # Dual-process launcher for Render ($PORT binding)
├── requirements.txt        # Lightweight dependencies (< 512 MB RAM)
├── Home.py                 # Streamlit landing page with subprocess fallback
├── ui_helpers.py           # Responsive styles, auth gate, privacy controls
├── pages/                  # Streamlit multi-page interface
│   ├── 1_Candidate_Analyzer.py
│   ├── 2_Recruiter_Dashboard.py
│   └── 3_Reports.py
└── app/                    # Internal FastAPI application
    ├── main.py             # FastAPI app with security headers & rate limiting
    ├── config.py           # Environment and settings management
    ├── db.py               # SQLite engine and 24-hr auto-purge logic
    ├── models.py           # Encrypted database models
    ├── schemas.py          # Strict Pydantic v2 schemas (extra="forbid")
    ├── security.py         # Fernet encryption, auth, budget guard, upload checks
    ├── routers/            # Modular API endpoints
    ├── services/           # Parsing, extraction, matching, ranking, reports
    └── data/
        └── skills_taxonomy.json  # 501 normalized skills with aliases
```
