```Dockerfile
###############################################################################
# PulseStream Nexus – Production Dockerfile
#
# This multi-stage build produces a slim, secure, and dependency-pinned image
# for the PulseStream Nexus data-streaming platform.
#
# Key points
#  - Builder stage installs all build-time deps & Python wheels
#  - Runtime stage contains only required artifacts (non-root user)
#  - OpenJDK is included for Spark / Beam back-fills
#  - Health-check ensures container liveness
#  - Tuned for Kubernetes & docker-compose deployments
###############################################################################

#############################
# 1) Builder ─────────────────
#############################
FROM python:3.11-slim-bookworm AS builder

# ---- Metadata --------------------------------------------------------------
LABEL org.opencontainers.image.title="PulseStream Nexus" \
      org.opencontainers.image.description="High-volume social data ingestion & streaming analytics." \
      org.opencontainers.image.vendor="PulseStream" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/pulsestream/nexus"

# ---- Environment -----------------------------------------------------------
ARG POETRY_VERSION=1.8.2
ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    DEBIAN_FRONTEND=noninteractive

# ---- System build deps -----------------------------------------------------
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        git \
        curl \
        ca-certificates \
        openjdk-17-jdk-headless \
        libpq-dev \
        libffi-dev \
        libssl-dev \
        libmagic-dev \
        gnupg && \
    rm -rf /var/lib/apt/lists/*

# ---- Python dependencies ---------------------------------------------------
RUN python -m pip install --upgrade pip && \
    pip install "poetry==${POETRY_VERSION}"

# Copy dependency descriptors first to leverage Docker cache.
WORKDIR /src
COPY pyproject.toml poetry.lock ./

# Install deps only (no dev, no tests).
RUN poetry install --no-dev

# Copy source code (only after deps to maximize layer caching)
COPY ./src ./src

#############################
# 2) Runtime ────────────────
#############################
FROM python:3.11-slim-bookworm AS runtime

# ---- Non-root user ---------------------------------------------------------
ARG USER=app
ARG UID=10001
ARG GID=10001

RUN groupadd -g "${GID}" "${USER}" && \
    useradd --create-home --uid "${UID}" --gid "${GID}" --shell /sbin/nologin "${USER}"

# ---- System runtime deps ---------------------------------------------------
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        openjdk-17-jre-headless \
        libmagic1 \
        curl && \
    # Clean up apt artifacts to keep image small
    rm -rf /var/lib/apt/lists/*

# Copy Python environment from builder stage
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application sources (for runtime introspection)
WORKDIR /opt/pulsestream
COPY --from=builder /src/src ./src

# Expose ports (8080 – REST gateway, 9092 – Kafka side-car if enabled)
EXPOSE 8080 9092

# Runtime Environment Variables
ENV PYTHONUNBUFFERED=1 \
    OTEL_TRACES_EXPORTER=otlp \
    PULSTREAM_ENVIRONMENT="docker"

# Healthcheck – assume platform provides /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD \
    curl -f http://localhost:8080/health || exit 1

# Switch to non-root user for security
USER "${USER}"

# Default command (overridable)
ENTRYPOINT ["pulsestream"]
CMD ["nexus", "start", "--config", "/etc/pulsestream/config.yaml"]
```
