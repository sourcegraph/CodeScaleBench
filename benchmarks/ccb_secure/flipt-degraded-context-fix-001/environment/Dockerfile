FROM golang:1.21-bookworm

WORKDIR /workspace

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone Flipt at pinned commit
RUN git clone --filter=blob:none --no-checkout https://github.com/flipt-io/flipt.git . && \
    git checkout 3d5a345f94c2adc8a0eaa102c189c08ad4c0f8e8 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Download Go modules
RUN go mod download 2>/dev/null || true

# Simulate degraded context: remove key dependency files
# These files exist in the Sourcegraph index but not in the local workspace
# The agent must infer types from usage patterns or search remotely via MCP
RUN rm -f internal/storage/storage.go && \
    rm -f rpc/flipt/evaluation/evaluation.proto && \
    rm -f rpc/flipt/flipt.proto
