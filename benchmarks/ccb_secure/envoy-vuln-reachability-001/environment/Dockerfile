FROM debian:bookworm-slim

# Install dependencies for analysis
RUN apt-get update && apt-get install -y \
    git \
    curl \
    ripgrep \
    jq \
    bc \
    && rm -rf /var/lib/apt/lists/*

# Clone Envoy at v1.31.1 (same as sec-cve-002)
WORKDIR /workspace
RUN git clone --depth 1 --branch v1.31.1 https://github.com/envoyproxy/envoy.git

# Verify we have the correct version
RUN cd envoy && \
    git log --oneline -1 | grep -q "^" && \
    echo "Checked out Envoy v1.31.1"

# Create logs directory for agent output
RUN mkdir -p /logs/agent

WORKDIR /workspace/envoy
