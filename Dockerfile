# ResumeIQ — Unified Docker Container for Render.com (and Docker-compatible platforms)
FROM python:3.12-slim

# Prevent Python from writing .pyc files and buffer outputs
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENV=production \
    PORT=7860

# Install lightweight system tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root application user with UID 1000
RUN useradd -m -u 1000 appuser

WORKDIR /home/appuser/app

# Install Python dependencies first for optimal layer caching
COPY --chown=appuser:appuser requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY --chown=appuser:appuser . .

# Ensure start script has executable permissions and LF line endings
RUN chmod +x start.sh

# Switch to non-root user
USER appuser

# Render dynamically assigns $PORT at runtime
EXPOSE 7860

CMD ["./start.sh"]
