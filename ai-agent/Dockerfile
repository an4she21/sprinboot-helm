# ---- Build Stage: install dependencies ----
FROM python:3.11-slim AS builder

WORKDIR /build

# Cache pip downloads — only re-runs when requirements.txt changes
COPY requirements.txt .
RUN pip download --no-cache-dir --dest /wheels -r requirements.txt

# ---- Runtime Stage ----
FROM python:3.11-slim

WORKDIR /app

# Security: non-root user
RUN addgroup --system agent && adduser --system --ingroup agent agent

# Install from pre-downloaded wheels (faster, no build tools in final image)
COPY requirements.txt .
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links=/wheels /wheels/*.whl 2>/dev/null \
    || pip install --no-cache-dir -r requirements.txt \
    && rm -rf /wheels

# Copy agent code
COPY main.py k8s_client.py models.py __init__.py ./

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Health check (matches the /health endpoint)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

USER agent

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
