# syntax=docker/dockerfile:1.4

######################################################################
# CrowdPay Connect – Transaction Service
#
# This Dockerfile produces a small, secure, production-ready container
#   for the `transaction_service` micro-service.
#
# Pattern:
#   1. Builder stage   – installs build dependencies and wheels.
#   2. Runtime stage   – copies wheels + source, drops build deps,
#                        runs as non-root, exposes healthchecks.
#
# Best practices applied:
#   • Multi-stage build for minimal image size
#   • Non-root execution
#   • Layer caching for Python wheels
#   • Explicit, pinned dependency installation
#   • Read-only filesystem with writable tmpfs
######################################################################

############################
# 1 – Builder Stage
############################
FROM python:3.11-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=60

# Install system build deps *only* for wheel compilation
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive \
    apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libc6-dev \
        libpq-dev \
        git && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy dependency files first to maximise cache hits
COPY services/transaction_service/pyproject.toml \
     services/transaction_service/poetry.lock \
     ./ 

# Install Poetry in the builder image
ARG POETRY_VERSION=1.6.1
RUN pip install --upgrade "poetry==${POETRY_VERSION}"

# Build wheelhouse with all prod dependencies
RUN poetry export --without-hashes --only main \
      | pip wheel --wheel-dir /build/wheels -r /dev/stdin

############################
# 2 – Runtime Stage
############################
FROM python:3.11-slim-bookworm

LABEL org.opencontainers.image.title="CrowdPay Connect – Transaction Service" \
      org.opencontainers.image.description="Microservice responsible for orchestrating atomic, multi-currency transactions via Saga pattern." \
      maintainer="CrowdPay Platform Engineering <eng@crowdpay.io>" \
      org.opencontainers.image.source="https://github.com/crowdpay/connect" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # restrict Python to UTF-8 ensuring consistent I/O across locales
    PYTHONIOENCODING=utf-8 \
    # poetry creates editable installs by default; we install wheels
    PIP_NO_CACHE_DIR=on

# create app group/user
RUN addgroup --system app && adduser --system --ingroup app app

# Runtime dependencies for psycopg2, etc.
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive \
    apt-get install -y --no-install-recommends \
        libpq5 \
        libffi8 \
        ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy wheels from builder & install
COPY --from=builder /build/wheels /tmp/wheels
RUN pip install --no-cache-dir --no-index --find-links=/tmp/wheels /tmp/wheels/* \
    && rm -rf /tmp/wheels

# Copy application source
WORKDIR /app
COPY services/transaction_service/ ./ 

# Ensure correct permissions
RUN chown -R app:app /app

USER app

# Configure the container.
EXPOSE 8080
ENV GUNICORN_CMD_ARGS="--bind 0.0.0.0:8080 --workers 4 --worker-class uvicorn.workers.UvicornWorker --timeout 120"

# Healthcheck pings the built-in "/health" endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl --fail http://localhost:8080/health || exit 1

# Restrict filesystem to read-only (mutable dirs via tmpfs/volumes)
VOLUME /data
RUN chmod 555 /app
CMD [ "gunicorn", "transaction_service.main:app" ]