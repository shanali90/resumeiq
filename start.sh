#!/bin/bash
set -e

echo "=========================================="
echo "Starting ResumeIQ Production Services"
echo "Target Platform: Render.com / Docker"
echo "Public Port: ${PORT:-7860}"
echo "=========================================="

# 1. Start internal FastAPI backend on 127.0.0.1:8000 (single worker, minimal RAM)
echo "Launching FastAPI backend (internal 127.0.0.1:8000)..."
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log &
BACKEND_PID=$!

# 2. Wait for FastAPI health check before starting frontend
echo "Awaiting FastAPI readiness..."
for i in {1..30}; do
    if curl -s http://127.0.0.1:8000/health > /dev/null; then
        echo "FastAPI backend is ready!"
        break
    fi
    sleep 0.5
done

# 3. Launch public Streamlit frontend bound dynamically to $PORT
echo "Launching Streamlit frontend on port ${PORT:-7860}..."
exec streamlit run Home.py \
    --server.port "${PORT:-7860}" \
    --server.address 0.0.0.0 \
    --server.headless true \
    --server.enableCORS false \
    --server.enableXsrfProtection true \
    --browser.gatherUsageStats false
