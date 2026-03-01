FROM ubuntu:22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Clone Cilium at a stable release tag
RUN git clone --depth 1 https://github.com/sg-evals/cilium--v1.16.5.git /workspace

WORKDIR /workspace
