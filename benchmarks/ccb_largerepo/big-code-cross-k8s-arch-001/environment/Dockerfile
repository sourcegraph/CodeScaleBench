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

# Clone Kubernetes at pinned commit (v1.30.0)
# All four sub-projects (apiextensions-apiserver, client-go, apimachinery, api)
# are in the staging/ directory of the monorepo
RUN git clone --filter=blob:none --no-checkout https://github.com/kubernetes/kubernetes.git . && \
    git checkout v1.30.0 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Copy tests (verifier, ground truth)
COPY tests/ /workspace/tests/
