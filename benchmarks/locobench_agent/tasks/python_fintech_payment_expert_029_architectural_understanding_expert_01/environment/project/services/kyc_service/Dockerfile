# syntax=docker/dockerfile:1

#######################################################################
# CrowdPay Connect – KYC Service                                      #
# ------------------------------------------------------------------- #
# A production-ready, multi-stage Dockerfile that packages the KYC    #
# micro-service. The final image is lean, runs as a non-root user,    #
# and follows container-security best-practices.                      #
#######################################################################

############################
# 1. Builder Stage
############################
FROM python:3.10-slim AS builder

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git && \
    rm -rf /var/lib/apt/lists/*

# Configure environment
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# Add non-root application user (will be re-used in final stage)
ARG APP_USER=appuser
ARG APP_UID=10001
RUN adduser \
      --disabled-password \
      --gecos "" \
      --uid ${APP_UID} \
      ${APP_USER}

WORKDIR /app

# -- Dependency installation -----------------------------------------
# We copy only dependency manifests first to leverage Docker cache.
COPY services/kyc_service/pyproject.toml \
     services/kyc_service/poetry.lock \
     ./

# Install Poetry & project dependencies into the global site-packages
RUN pip install --upgrade pip poetry && \
    # Disable virtual-env creation so libs go to /usr/local
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --only main

############################
# 2. Runtime Stage
############################
FROM python:3.10-slim

LABEL org.opencontainers.image.title="CrowdPay Connect – KYC Service" \
      org.opencontainers.image.description="Performs real-time KYC and AML verification workflows." \
      org.opencontainers.image.url="https://github.com/crowdpay/connect" \
      org.opencontainers.image.vendor="CrowdPay" \
      org.opencontainers.image.source="https://github.com/crowdpay/connect/services/kyc_service" \
      maintainer="CrowdPay DevOps <devops@crowdpay.example>"

# -- Install minimal runtime tools -----------------------------------
RUN apt-get update && \
    apt-get install -y --no-install-recommends tini && \
    rm -rf /var/lib/apt/lists/*

# Re-create the non-root user (UID/GID must match builder stage)
ARG APP_USER=appuser
ARG APP_UID=10001
RUN adduser \
      --disabled-password \
      --gecos "" \
      --uid ${APP_UID} \
      ${APP_USER}

WORKDIR /app

# Copy python dependencies from builder image
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY services/kyc_service/ .

# Runtime environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_MODULE="kyc_service.main:app" \
    GUNICORN_CMD_ARGS="--config python:kyc_service.config.gunicorn" \
    PORT=8080

USER ${APP_USER}

# Expose the service port
EXPOSE ${PORT}

# Health check (expects a /healthz endpoint)
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:${PORT}/healthz || exit 1

# Use tini as PID 1 for proper signal propagation
ENTRYPOINT ["/usr/bin/tini", "--"]

# Launch the ASGI app via Gunicorn with Uvicorn workers
CMD ["gunicorn", "kyc_service.main:app"]