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

# Clone Argo CD at a stable release tag
# v2.13.2 is a recent stable release with well-established structure
RUN git clone --filter=blob:none --no-checkout https://github.com/argoproj/argo-cd.git . && \
    git checkout v2.13.2 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
