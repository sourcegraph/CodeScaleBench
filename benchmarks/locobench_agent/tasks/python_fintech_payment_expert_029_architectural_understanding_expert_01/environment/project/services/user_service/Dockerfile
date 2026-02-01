```Dockerfile
###############################################################################
# CrowdPay Connect – User Service
# Dockerfile
#
#   This Dockerfile builds a hardened, minimal container image for the
#   `user_service` micro-service.  The service is assumed to be a FastAPI
#   (or other ASGI-compatible) application that is served with Gunicorn/Uvicorn.
#
#   Design goals:
#     1. Multi-stage build to keep runtime image small.
#     2. Non-root execution for strict “Security-by-Design”.
#     3. Explicit dependency pinning & caching efficiency.
#     4. Healthcheck for orchestration readiness probes.
###############################################################################

########################
# 1️⃣  Build Stage
########################
FROM python:3.11-slim-bookworm AS builder

# Install compile-time system dependencies
RUN apt-get update \
 && apt-get install --no-install-recommends -y \
      build-essential \
      gcc \
      libpq-dev \
      curl \
      git \
      ca-certificates \
 # Clean up APT when done to keep layers lean
 && apt-get purge -y --auto-remove \
 && rm -rf /var/lib/apt/lists/*

# Enable pip cache for later stages
ENV PIP_CACHE_DIR=/root/.cache/pip

# Install pip-tools to compile deterministic dependency locks
RUN python -m pip install --upgrade pip \
 && pip install pip-tools

WORKDIR /app

# Copy requirement manifests (only) for dependency resolution & cache
COPY requirements ./requirements

# Compile and install production dependencies (wheel-compiled)
RUN pip-compile \
        requirements/prod.in \
        --resolver=backtracking \
        --output-file=requirements.lock \
 && pip install --no-cache-dir -r requirements.lock

# Copy application source for subsequent packaging (optional wheel build)
COPY user_service ./user_service

########################
# 2️⃣  Runtime Stage
########################
FROM python:3.11-alpine3.19 AS runtime

# Install runtime system dependencies (libc-compat, psycopg2, etc.)
RUN apk add --no-cache \
      libpq \
      libstdc++ \
      curl

# Copy virtual environment from builder to runtime
COPY --from=builder /usr/local /usr/local

# Create non-root user & group
RUN addgroup  --system crowdgrp \
 && adduser   --system --ingroup crowdgrp --home /app crowdusr

WORKDIR /app
USER crowdusr:crowdgrp

# Copy application source code (for runtime only files)
COPY --from=builder /app/user_service ./user_service

# By default, disable bytecode compilation & enable unbuffered stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_MODULE="user_service.main:app" \
    GUNICORN_CMD_ARGS="--workers 3 --worker-class uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000 --timeout 30"

EXPOSE 8000

########################
# 3️⃣  Entrypoint
########################
# Healthcheck leverages service’s `/health/live` endpoint
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD curl --fail http://localhost:8000/health/live || exit 1

ENTRYPOINT ["gunicorn"]

CMD ["${APP_MODULE}"]
```