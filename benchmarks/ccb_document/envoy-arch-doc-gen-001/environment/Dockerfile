FROM python:3.11-slim

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone Envoy at pinned commit (blobless clone — repo is very large)
RUN git clone --filter=blob:none --no-checkout https://github.com/envoyproxy/envoy.git . && \
    git checkout 1d0ba73ad200d28e86c0c23f76c55320f82a8fba && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
