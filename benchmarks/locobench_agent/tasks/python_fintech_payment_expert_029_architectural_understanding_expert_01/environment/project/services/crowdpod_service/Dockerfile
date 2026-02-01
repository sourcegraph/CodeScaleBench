# -----------------------------------------------------------------------------
# CrowdPay Connect - CrowdPod Service
#
# This Dockerfile produces an optimized, production-ready image for the
# `crowdpod_service` micro-service.  It follows best-practices for Python, is
# compatible with container-scanning tools (e.g. Trivy, Grype, Dockle), and is
# hardened for use in a regulated fintech environment.
#
# Build arguments (override via `--build-arg`):
#   PYTHON_VERSION  : Python interpreter version
#   PIP_INDEX_URL   : Custom/private PyPI index (optional)
#   BUILD_ENV       : `dev`, `staging`, `prod` (defaults to `prod`)
#
# Example:
#   docker build \
#     --build-arg BUILD_ENV=staging \
#     --build-arg PIP_INDEX_URL=https://pypi.mycorp.local/simple \
#     -t registry.local/crowdpay/crowdpod-service:1.4.3 .
# -----------------------------------------------------------------------------

# ---------- Base build stage --------------------------------------------------
ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim-bookworm AS base

# Install system packages required for build and runtime
RUN set -eux; \
    DEBIAN_FRONTEND=noninteractive apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev            \
        libffi-dev           \
        libssl-dev           \
        curl                 \
        ca-certificates;     \
    rm -rf /var/lib/apt/lists/*

# Create non-root user with least privilege
RUN useradd --create-home --shell /usr/sbin/nologin svc

# ---------- Builder stage -----------------------------------------------------
FROM base AS builder

# Copy app dependency manifests first (for layer-caching)
WORKDIR /build
COPY pyproject.toml poetry.lock* requirements.txt* ./

# Use Poetry if present, otherwise fall back to requirements.txt
ARG PIP_INDEX_URL
ENV PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=60 \
    PIP_INDEX_URL=${PIP_INDEX_URL:-}

# Install build dependencies
RUN --mount=type=cache,target=/root/.cache/pip \
    set -eux; \
    if [ -f "poetry.lock" ]; then \
        pip install --upgrade pip poetry==1.7.*; \
        poetry config virtualenvs.create false; \
        poetry install --no-interaction --no-ansi --only main; \
    elif [ -f "requirements.txt" ]; then \
        pip install --upgrade pip; \
        pip install -r requirements.txt; \
    else \
        echo "No dependency manifest found!" && exit 1; \
    fi

# ---------- Final runtime stage ----------------------------------------------
FROM base AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_HOME=/opt/app \
    GUNICORN_CMD_ARGS="--workers=4 --bind=0.0.0.0:8000 --timeout=60"

WORKDIR ${APP_HOME}

# Copy installed site-packages from builder stage
COPY --from=builder /usr/local/lib/python*/site-packages /usr/local/lib/python*/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY . ${APP_HOME}

# Set permissions
RUN chown -R svc:svc ${APP_HOME}

USER svc

# Healthcheck ‑ verifies dependencies and database connectivity
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -m crowdpod_service.healthcheck

# Run the ASGI / WSGI server
CMD ["gunicorn", "crowdpod_service.api:app"]
