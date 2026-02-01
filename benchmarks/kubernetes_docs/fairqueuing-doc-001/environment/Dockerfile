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

# Clone the actual Kubernetes repository
RUN git clone --depth 1 https://github.com/kubernetes/kubernetes.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# SURGICAL: Remove ONLY the target doc.go (not recursive!)
RUN rm -f staging/src/k8s.io/apiserver/pkg/util/flowcontrol/fairqueuing/queueset/doc.go
# Strip "// Package ..." line from files in the immediate directory only
RUN find staging/src/k8s.io/apiserver/pkg/util/flowcontrol/fairqueuing/queueset -maxdepth 1 -name "*.go" -exec sed -i '/^\/\/ Package/d' {} +

# Create test directory for verifier
RUN mkdir -p /workspace/tests

# Create /app directory for MCP config upload compatibility
RUN mkdir -p /app
