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

# Clone the actual Kubernetes repository
# This ensures BOTH baseline and MCP agents have identical file access
RUN git clone --depth 1 https://github.com/kubernetes/kubernetes.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Task setup complete
# Note: Both baseline and MCP agents now have access to the real Kubernetes source.
# Baseline will use local grep/find/rg. MCP will use Sourcegraph semantic search.
