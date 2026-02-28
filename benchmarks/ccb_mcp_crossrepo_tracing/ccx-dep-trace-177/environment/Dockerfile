FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Base tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    curl \
    python3 \
    g++ make \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Clone local checkout repos (baseline config: agent has local access to these)
RUN git clone --depth 1 https://github.com/sg-evals/envoy--v1.31.2 /workspace/envoy--v1.31.2
RUN git clone --depth 1 https://github.com/sg-evals/data-plane-api--84e84367 /workspace/data-plane-api--84e84367
RUN git clone --depth 1 https://github.com/sg-evals/go-control-plane--71637ad6 /workspace/go-control-plane--71637ad6
RUN git clone --depth 1 https://github.com/sg-evals/grpc--957dba5e /workspace/grpc--957dba5e

# Initialize git identity for agent commits
RUN git config --global user.email "agent@example.com" && \
    git config --global user.name "Agent" && \
    git config --global safe.directory '*'

# Create log directories
RUN mkdir -p /logs/agent /logs/verifier

# Pre-create claude user and set ownership at build time so Harbor's
# runtime chown is a no-op (avoids 15-30 min delay on large repos).
RUN (adduser --disabled-password --gecos '' claude 2>/dev/null || true) && \
    for d in /workspace /app /testbed /logs; do [ -d "$d" ] && chown -R claude:claude "$d"; done || true

ENTRYPOINT []
