FROM ubuntu:22.04

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    python3 \
    python3-pip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Clone Envoy at pinned commit (v1.32.1 stable release)
RUN git clone --depth 1 https://github.com/sg-evals/envoy--v1.32.1.git /workspace

WORKDIR /workspace

# Create logs directory for output
RUN mkdir -p /logs/agent
