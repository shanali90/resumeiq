"""ResumeIQ FastAPI application entry point.

Provides RESTful endpoints for:
- Resume parsing and structured profile extraction
- Job description analysis
- Resume vs JD matching and scoring
- Recruiter multi-candidate ranking
- PDF and JSON report downloads
- Health monitoring
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import init_db, cleanup_old_records
from app.routers import jobs, matching, reports, resumes
from app.schemas import HealthResponse
from app.security import get_rate_limiter
from app.services.matcher import get_embedding_model

# Configure logging
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("resumeiq")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for application startup and shutdown."""
    logger.info("Initializing ResumeIQ backend...")
    init_db()

    # Pre-warm embedding model in background if possible
    try:
        get_embedding_model()
    except Exception as exc:
        logger.warning("Could not pre-warm embedding model: %s", exc)

    logger.info("ResumeIQ backend startup complete.")
    yield
    logger.info("Shutting down ResumeIQ backend...")


app = FastAPI(
    title="ResumeIQ API",
    description="AI-Powered Resume Analyzer & Intelligent Job Matching System",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

# Production-tailored CORS configuration
cors_origins = (
    [
        "http://127.0.0.1:8501",
        "http://localhost:8501",
        "http://127.0.0.1:7860",
        "http://localhost:7860",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]
    if settings.is_production
    else ["*"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers_and_rate_limit(request: Request, call_next):
    """Enforce standard security headers and sliding-window rate limiting on sensitive routes."""
    path = request.url.path

    # Apply rate limiting to heavy and upload endpoints
    if path in ("/resumes/analyze", "/resumes/upload", "/matching/match", "/matching/rank"):
        client_ip = request.client.host if request.client else "127.0.0.1"
        limiter = get_rate_limiter()
        if not limiter.is_allowed(f"{client_ip}:{path}"):
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"detail": "Too many requests. Please wait a moment and try again."},
            )

    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response


@app.exception_handler(Exception)
async def sanitized_unhandled_exception_handler(request: Request, exc: Exception):
    """Conceal internal tracebacks in production while logging details securely."""
    logger.exception("Unhandled exception processing request to %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred. Please try again later."},
    )

# Register routers
app.include_router(resumes.router)
app.include_router(jobs.router)
app.include_router(matching.router)
app.include_router(reports.router)


@app.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    tags=["System"],
    summary="Service health check",
)
def health_check() -> HealthResponse:
    """Verify application health and availability of external services."""
    model = get_embedding_model()
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        gemini_available=settings.has_gemini_key,
        embedding_model_loaded=model is not None,
    )


@app.get("/", tags=["System"], include_in_schema=False)
def root_redirect():
    """Root endpoint info."""
    return {
        "app": "ResumeIQ",
        "version": "1.0.0",
        "documentation": "/docs",
        "health": "/health",
    }
