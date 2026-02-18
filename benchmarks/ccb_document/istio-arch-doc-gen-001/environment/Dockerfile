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

# Clone Istio at pinned commit (blobless clone — repo is large)
RUN git clone --filter=blob:none --no-checkout https://github.com/istio/istio.git . && \
    git checkout f8af3caeb1960d4cb1db5c4c0d4913c366625c71 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
