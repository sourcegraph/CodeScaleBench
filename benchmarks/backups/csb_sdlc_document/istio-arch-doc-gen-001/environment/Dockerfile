FROM python:3.11-slim

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Clone Istio at pinned commit (blobless clone — repo is large)
RUN git clone --depth 1 https://github.com/sg-evals/istio--f8af3cae.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
