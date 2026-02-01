# syntax=docker/dockerfile:1.4
################################################################################
# LedgerQuest Engine – GPU-Accelerated Rendering Worker
#
# This Dockerfile builds the container image that powers burst rendering tasks
# (ray-tracing, video composition, etc.) executed by AWS Fargate’s GPU profiles.
#
# Key features
#  • Multi-stage build for tiny runtime layers
#  • Deterministic, cached Python dependency resolution
#  • Non-root execution with read-only root filesystem
#  • Health-check & logging conventions expected by LedgerQuest Orchestrator
#
# Docker BuildKit is required (`DOCKER_BUILDKIT=1`).
################################################################################

############### Build Stage ####################################################

FROM python:3.11-slim-bookworm AS builder

# Install OS build tooling and libraries required to compile Python wheels
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential \
        git \
        cmake \
        libgl1-mesa-dev \
        libglu1-mesa-dev \
        && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /tmp/build

# Copy project dependency manifests first (leveraging BuildKit cache)
COPY rendering/requirements.txt /tmp/build/requirements.txt

# Create a virtual environment for deterministic, relocatable installs
RUN python -m venv /opt/venv && \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip wheel && \
    /opt/venv/bin/pip install --no-cache-dir -r /tmp/build/requirements.txt

# `builder` stage now contains a self-contained venv at /opt/venv
################################################################################


############### Runtime Stage ##################################################

# CUDA 12.3 base with minimal runtime components
FROM nvidia/cuda:12.3.0-runtime-ubuntu22.04 AS runtime

ARG BUILD_COMMIT=unknown
ARG BUILD_TIMESTAMP=unknown

# Metadata labels aid SBOM generation and image scanning
LABEL org.opencontainers.image.source="https://github.com/LedgerQuest/engine" \
      org.opencontainers.image.description="GPU-enabled renderer for LedgerQuest Engine" \
      org.opencontainers.image.revision="${BUILD_COMMIT}" \
      org.opencontainers.image.created="${BUILD_TIMESTAMP}"

# Install runtime OS packages (no compilers, keep attack surface small)
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        ca-certificates \
        curl \
        tini \
        && \
    rm -rf /var/lib/apt/lists/*

# Copy Python virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Copy application code
WORKDIR /opt/ledgerquest
COPY rendering/ ./rendering

# Create non-root user for runtime
RUN groupadd --system --gid 10001 ledger && \
    useradd  --system --gid ledger --uid 10001 --create-home ledger

USER ledger

# Entrypoint & command
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "ledgerquest.rendering.worker"]

# Heath-check executed by ECS / Kubernetes
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD \
    python -m ledgerquest.rendering.healthcheck || exit 1

# Expose port used by internal gRPC control channel (if applicable)
EXPOSE 8080

# Ensure root filesystem is read-only at runtime (defence-in-depth)
# The orchestrator may override, but this is the sane default.
RUN chmod -R o-w /opt/ledgerquest /opt/venv
VOLUME ["/tmp"]  # Writable scratch space mapped to ephemeral storage

################################################################################
# Build example (with Git metadata):
#   docker build \
#     --build-arg BUILD_COMMIT=$(git rev-parse --short HEAD) \
#     --build-arg BUILD_TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
#     -t ledgerquest/renderer:latest \
#     -f LedgerQuestEngine/rendering/Dockerfile .
################################################################################