FROM ubuntu:22.04

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    && rm -rf /var/lib/apt/lists/*

# Clone Envoy at v1.34.0 release (pinned SHA)
RUN git clone --filter=blob:none --no-checkout https://github.com/envoyproxy/envoy.git . && \
    git checkout d7809ba2b07fd869d49bfb122b27f6a7977b4d94 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
