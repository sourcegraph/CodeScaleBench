FROM debian:bookworm-slim

# Install dependencies for analysis
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ripgrep \
    jq \
    bc \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Clone Envoy at v1.31.2 (pinned mirror, replaces fallback clone)
WORKDIR /workspace
RUN git clone --depth 1 https://github.com/sg-evals/envoy--v1.31.2.git envoy

# Create logs directory for agent output
RUN mkdir -p /logs/agent

WORKDIR /workspace/envoy
