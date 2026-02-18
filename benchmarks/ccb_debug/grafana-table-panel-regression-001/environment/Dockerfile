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

# Clone Grafana at the target commit (v38 migration regression)
# Commit 26d36ec contains the migration fix; we check out its parent to get the broken state
RUN git clone --filter=blob:none --no-checkout https://github.com/grafana/grafana.git . && \
    git checkout 26d36ec~1 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
