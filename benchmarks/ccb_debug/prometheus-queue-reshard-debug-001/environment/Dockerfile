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

# Clone Prometheus at the target commit (before remote-write resharding fix)
# Commit ba14bc4 is the broken change (deprecated per-QM counters);
# revert commit 6806b68 fixes it
RUN git clone --filter=blob:none --no-checkout https://github.com/prometheus/prometheus.git . && \
    git checkout ba14bc4 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
