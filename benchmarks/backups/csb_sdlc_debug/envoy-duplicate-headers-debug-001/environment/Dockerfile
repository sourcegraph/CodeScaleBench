FROM ubuntu:22.04

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    python3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Clone Envoy at the target commit (before router header mutation fix)
# PR #40856 (commit 25f893b) fixes the bug; this mirror is pinned to its parent (3c500753)
RUN git clone --depth 1 https://github.com/sg-evals/envoy--3c500753.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
