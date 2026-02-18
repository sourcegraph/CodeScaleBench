FROM golang:1.23-bookworm

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    python3-pip \
    npm

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone the actual Kubernetes repository at pinned commit (v1.30.0)
# This ensures BOTH baseline and MCP agents have identical file access
RUN git clone --filter=blob:none --no-checkout https://github.com/kubernetes/kubernetes.git . && \
    git checkout 11602f083ca275dcfd4341641ae7fe338b7f6f69 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Task setup complete
# Note: Both baseline and MCP agents now have access to the real Kubernetes source.
# Baseline will use local grep/find/rg. MCP will use Sourcegraph semantic search.
