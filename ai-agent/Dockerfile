# ---- Build Stage: compile wheels with C deps ----
FROM python:3.11-alpine AS builder

WORKDIR /build

# Build dependencies for C extensions (cryptography, pydantic-core, cffi)
RUN apk add --no-cache gcc musl-dev libffi-dev

# Cache pip wheels — only re-runs when requirements.txt changes
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir=/wheels -r requirements.txt

# ---- Runtime Stage ----
FROM python:3.11-alpine

WORKDIR /app

# Patch OS-level vulnerabilities in Alpine packages
RUN apk update && apk upgrade --no-cache && rm -rf /var/cache/apk/*

# Security: non-root user (Alpine syntax: -S = system, -G = group)
RUN addgroup -S agent && adduser -S agent -G agent

# Install from pre-built wheels (fast, no build tools in final image)
COPY requirements.txt .
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# Strip build-time packages with known CVEs (not needed at runtime)
# - setuptools: vendored jaraco.context CVE-2026-23949, wheel CVE-2026-24049
# - pip: not needed after install
RUN pip uninstall -y setuptools pip wheel 2>/dev/null || true \
    && rm -rf /usr/local/lib/python3.11/site-packages/setuptools/ 2>/dev/null || true

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
