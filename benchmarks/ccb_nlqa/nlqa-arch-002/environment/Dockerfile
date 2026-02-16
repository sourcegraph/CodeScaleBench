FROM ubuntu:22.04

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    && rm -rf /var/lib/apt/lists/*

# Clone Istio at v1.24.3 release (pinned SHA)
RUN git clone --filter=blob:none --no-checkout https://github.com/istio/istio.git . && \
    git checkout 44d0e58e49d0dc89e27fc4f8679c68132d46b887 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
