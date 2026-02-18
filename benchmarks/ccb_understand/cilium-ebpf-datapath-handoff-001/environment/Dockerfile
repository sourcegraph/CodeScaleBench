FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Clone Cilium at a stable release tag
RUN git clone https://github.com/cilium/cilium.git /workspace && \
    cd /workspace && \
    git checkout v1.16.5

WORKDIR /workspace
