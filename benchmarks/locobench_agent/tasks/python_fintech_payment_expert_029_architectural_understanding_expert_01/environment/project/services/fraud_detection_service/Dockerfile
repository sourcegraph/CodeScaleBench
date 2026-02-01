# syntax=docker/dockerfile:1

###############################################################################
#                      CrowdPay Connect – Fraud Detection                     #
#                          Multi-Stage Production Image                       #
###############################################################################
# This Dockerfile builds a slim, secure runtime container for the
# `fraud_detection_service` micro-service.  It follows best practices:
#
# • Multi-stage build  ──────────────────────►  smallest possible image size
# • Non-root runtime user ───────────────────►  surface-area reduction
# • Layer caching with pip wheelhouse ───────►  faster CI builds
# • Explicit / minimal OS packages ──────────►  security, reproducibility
# • Health-check & metadata labels ──────────►  observability & DevOps hygiene
###############################################################################

############################
# 1 — Build / Compile deps #
############################
FROM python:3.11-slim-bookworm AS builder

# Environment sanity.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false

# Workdir for dependency resolution
WORKDIR /build

# System-level build deps (cleaned up later)
RUN apt-get update && \
    apt-get install --no-install-recommends -y build-essential gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy only dependency manifests first to leverage Docker cache
COPY services/fraud_detection_service/pyproject.toml  .
COPY services/fraud_detection_service/poetry.lock      .

# Install Poetry to create a wheelhouse (cached for speed)
RUN pip install --no-cache-dir poetry==1.8.* && \
    poetry export --without-hashes --format=requirements.txt > requirements.txt && \
    pip wheel --no-cache-dir --wheel-dir /build/wheels -r requirements.txt


###########################
# 2 — Runtime / Final Img #
###########################
FROM python:3.11-slim-bookworm AS runtime

# Metadata for DevOps & SBOM tooling
LABEL org.opencontainers.image.title="CrowdPay Fraud-Detection Service" \
      org.opencontainers.image.description="Real-time risk scoring & transactional anomaly detection for CrowdPay Connect." \
      org.opencontainers.image.source="https://github.com/CrowdPay/crowdpay_connect" \
      org.opencontainers.image.licenses="Apache-2.0" \
      maintainer="engineering@crowdpay.io"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# -- Runtime user (non-root) --------------------------------------------------
RUN addgroup --system crowdpay && adduser --system --ingroup crowdpay crowdpay
USER crowdpay

# -- Minimal required OS libraries  ------------------------------------------
RUN apt-get update && \
    apt-get install --no-install-recommends -y libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

# -- Python deps (from builder wheelhouse) ------------------------------------
COPY --from=builder /build/wheels /wheels
COPY --from=builder /build/requirements.txt /
RUN python -m pip install --no-cache-dir --no-index --find-links=/wheels -r /requirements.txt && \
    rm -rf /wheels /requirements.txt

# -- Application code ---------------------------------------------------------
WORKDIR /app
COPY services/fraud_detection_service /app

# -- Port & healthcheck -------------------------------------------------------
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# -- Startup entrypoint -------------------------------------------------------
# NOTE: `start.py` bootstraps env-vars & launches Gunicorn/Uvicorn.
ENTRYPOINT ["python", "-m", "fraud_detection_service.start"]
