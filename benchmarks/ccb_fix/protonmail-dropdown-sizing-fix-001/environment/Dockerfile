# SWE-bench Pro Task Environment
# Instance: instance_protonmail__webclients-8be4f6cb9380fcd2e67bcb18cef931ae0d4b869c
# Repo: protonmail/webclients
#
# Multi-stage rebuild: the sweap-images for protonmail have corrupted system
# binaries (exec format / I/O error). We copy the pre-built /app directory
# (repo + node_modules + build artifacts) into a fresh Node.js base image.

FROM jefzda/sweap-images:protonmail.webclients-protonmail__webclients-8be4f6cb9380fcd2e67bcb18cef931ae0d4b869c AS source

FROM node:16.20.2-bullseye

RUN apt-get update && apt-get install -y --no-install-recommends \
    git jq python3 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=source /app /app

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

RUN git config user.email "agent@example.com" && \
    git config user.name "Agent"

ENTRYPOINT []
