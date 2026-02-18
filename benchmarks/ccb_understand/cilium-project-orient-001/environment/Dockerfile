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

# Clone Cilium at a stable release tag
# v1.16.5 is a recent stable release with well-established structure
RUN git clone --filter=blob:none --no-checkout https://github.com/cilium/cilium.git . && \
    git checkout v1.16.5 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
