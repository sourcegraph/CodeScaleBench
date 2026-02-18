FROM golang:1.23-bookworm

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone Kubernetes at the target commit (DRA AllocationMode change)
# Commit 2e534d6 is the change introducing multi-node AllocationMode:All
RUN git clone --filter=blob:none --no-checkout https://github.com/kubernetes/kubernetes.git . && \
    git checkout 2e534d6 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
