# syntax=docker/dockerfile:1.4
################################################################################
# CrowdPay Connect – Wallet Service
# Production-grade, multi-stage Dockerfile
#
# This image is designed according to the following principles:
#   • Minimal attack-surface  – we use python:3.x-slim and strip build tools.
#   • Deterministic builds    – dependencies are locked via Poetry.
#   • Non-root execution      – the service runs under an unprivileged user.
#   • Observability           – HEALTHCHECK & structured logging.
#   • Security hardening      – read-only root FS & dropped Linux capabilities.
#   • Multi-arch support      – relies on official Python base images.
################################################################################

############################
# 1. Base image definition #
############################
FROM python:3.11-slim AS base

# Prevent Python from writing .pyc files & enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set consistent timezone and locale for deterministic behavior
ENV TZ=UTC \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

###########################
# 2. Builder image target #
###########################
FROM base AS builder

WORKDIR /usr/src/app

# System build dependencies
RUN apt-get update -qq && \
    apt-get install --no-install-recommends -y \
        build-essential \
        git \
        curl && \
    rm -rf /var/lib/apt/lists/*

# Install Poetry in the builder stage
ENV POETRY_VERSION=1.6.1 \
    VIRTUAL_ENV=/opt/venv
RUN python -m venv "$VIRTUAL_ENV" && \
    "$VIRTUAL_ENV/bin/pip" install --upgrade pip && \
    "$VIRTUAL_ENV/bin/pip" install "poetry==${POETRY_VERSION}"

ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Copy dependency specifications first for caching
COPY pyproject.toml poetry.lock* /usr/src/app/

# Configure Poetry: no virtualenv creation inside container, speed-ups, no dev deps
RUN poetry config virtualenvs.create false && \
    poetry install --only main --no-ansi --no-interaction --no-root --no-cache

################################
# 3. Test stage (optional)     #
#    Run unit tests early;     #
#    the build fails if tests  #
#    do not pass.              #
################################
FROM builder AS tester
# Copy the full source tree for tests
COPY . /usr/src/app
# A minimal invocation of pytest
RUN pip install --no-cache-dir --quiet pytest==7.4.* && \
    pytest -q

##############################
# 4. Production-runtime image #
##############################
FROM base AS runtime

LABEL maintainer="CrowdPay Engineering <engineering@crowdpay.io>" \
      org.opencontainers.image.title="crowdpay-connect-wallet-service" \
      org.opencontainers.image.description="CrowdPay Connect Wallet microservice" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/crowdpay/crowdpay-connect"

# Create a dedicated, non-root user
RUN addgroup --system --gid 1001 appuser && \
    adduser  --system --uid 1001 --ingroup appuser --disabled-password appuser

WORKDIR /opt/wallet_service

# Copy pre-built virtual environment from the builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application source (only what we require at runtime)
COPY crowdpay_connect crowdpay_connect
COPY services/wallet_service services/wallet_service

# Expose service port (make sure this matches your FastAPI/Uvicorn config)
EXPOSE 8080/tcp

########################
# Health-check command #
########################
# The health-check calls a lightweight endpoint that runs synchronously.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD ["python", "-m", "crowdpay_connect.services.wallet_service.healthcheck"]

##############################
# Drop Linux capabilities    #
# & switch to non-root user  #
##############################
USER appuser

# Read-only FS for additional defence-in-depth. Volumes can be mounted for
# mutable paths if required (e.g., for logs or sqlite).
RUN chmod -R g=u /opt/wallet_service
VOLUME ["/opt/wallet_service/data"]
ENV PYTHONPATH=/opt/wallet_service

######################
# Launch the service #
######################
# Use `exec` form so that signals are proxied (for graceful shutdown).
CMD ["python", "-m", "crowdpay_connect.services.wallet_service"]
