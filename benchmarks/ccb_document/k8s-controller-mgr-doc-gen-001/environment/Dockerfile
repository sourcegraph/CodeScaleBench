FROM golang:1.23-bookworm

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    npm \
    ripgrep

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone the Kubernetes repository at pinned commit for reproducibility
# This ensures BOTH baseline and MCP agents have identical file access
RUN git clone --filter=blob:none --no-checkout https://github.com/kubernetes/kubernetes.git . && \
    git checkout 8c9c67c000104450cfc5a5f48053a9a84b73cf93 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# SURGICAL: Remove ONLY the target doc.go (not recursive!)
RUN rm -f pkg/kubelet/cm/doc.go
# Strip "// Package ..." line from files in the immediate directory only
RUN find pkg/kubelet/cm -maxdepth 1 -name "*.go" -exec sed -i '/^\/\/ Package/d' {} +

# Create test directory for verifier
RUN mkdir -p /workspace/tests

# Create /app directory for MCP config upload compatibility
RUN mkdir -p /app
