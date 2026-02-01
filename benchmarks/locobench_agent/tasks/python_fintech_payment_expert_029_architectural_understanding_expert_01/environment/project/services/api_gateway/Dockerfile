# syntax=docker/dockerfile:1.4
################################################################################
## CrowdPay Connect – API Gateway Service
## Production-grade, multi-stage build leveraging best practices for
## security, reproducibility, and performance.
################################################################################

############################
# Builder Stage
############################
FROM python:3.11-slim-bookworm AS builder

# Enable pip caching between builds
ENV PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system build dependencies
RUN apt-get update && \
    apt-get install --no-install-recommends -y build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# Install Poetry for dependency management
RUN curl -sSL https://install.python-poetry.org | python3 -

# Create app directory
WORKDIR /opt/api_gateway

# Copy only dependency descriptors first for better layer caching
COPY pyproject.toml poetry.lock* ./ 

# Install Python dependencies (including dev for type-checking/tests)
RUN poetry export --with dev --without-hashes --format=requirements.txt \
    | pip install --upgrade --no-cache-dir -r /dev/stdin && \
    poetry install --no-root --no-interaction --only main

# Copy source code
COPY . .

# Build binary wheel of the current package, if defined in pyproject
RUN poetry build -f wheel && \
    pip install --no-cache-dir dist/*.whl

############################
# Runtime Stage
############################
FROM python:3.11-slim-bookworm AS runtime

# Metadata
LABEL org.opencontainers.image.source="https://github.com/crowdpay/connect" \
      org.opencontainers.image.title="CrowdPay Connect – API Gateway" \
      org.opencontainers.image.description="Edge-facing gateway providing unified REST/GraphQL endpoints, routing, authN/Z, and rate-limiting." \
      org.opencontainers.image.maintainer="CrowdPay Engineering <eng@crowdpay.io>" \
      org.opencontainers.image.licenses="Apache-2.0"

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UWSGI_ENABLE_THREADS=1 \
    TZ=UTC

# Install runtime dependencies (no build tools)
RUN apt-get update && \
    apt-get install --no-install-recommends -y \
        tini \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /root/.local /root/.local
ENV PATH="/root/.local/bin:$PATH"

# Copy application code (already wheel-installed in builder)
COPY --from=builder /opt/api_gateway /opt/api_gateway
WORKDIR /opt/api_gateway

# Create non-root user for runtime
RUN addgroup --system --gid 2001 api && \
    adduser --system --uid 2001 --ingroup api --home /home/api api

USER api

# Health check – verifies application port is accepting connections
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD \
  wget --spider -q http://127.0.0.1:8080/health || exit 1

# Expose service port
EXPOSE 8080

# Entrypoint
ENTRYPOINT ["/usr/bin/tini", "--"]

# Production command line – adjustable via env (supports graceful reloads)
CMD ["uvicorn", "crowdpay_connect.api_gateway.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]