FROM ubuntu:22.04

# Install prerequisites
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Clone envoyproxy/envoy at pinned release tag v1.34.0
RUN git clone --filter=blob:none --no-checkout https://github.com/envoyproxy/envoy.git /workspace && \
    cd /workspace && \
    git checkout d7809ba2b07fd869d49bfb122b27f6a7977b4d94

WORKDIR /workspace
