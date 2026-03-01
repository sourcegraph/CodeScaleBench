FROM golang:1.23-bookworm

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    python3 \
    && rm -rf /var/lib/apt/lists/*

# Clone Kubernetes at the target commit (DRA AllocationMode change)
# Commit 2e534d6 is the change introducing multi-node AllocationMode:All
RUN git clone --depth 1 https://github.com/sg-evals/kubernetes--2e534d6.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
