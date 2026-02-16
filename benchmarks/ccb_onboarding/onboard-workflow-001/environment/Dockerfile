FROM ubuntu:22.04

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Clone Envoy at pinned commit (v1.32.1 stable release)
RUN git clone https://github.com/envoyproxy/envoy.git /workspace \
    && cd /workspace \
    && git checkout v1.32.1

WORKDIR /workspace

# Create logs directory for output
RUN mkdir -p /logs/agent
