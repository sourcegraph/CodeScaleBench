FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install git and dependencies
RUN apt-get update && \
    apt-get install -y git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Clone Cilium at pinned commit (v1.17.9)
RUN git clone --filter=blob:none --no-checkout https://github.com/cilium/cilium.git /workspace/cilium && \
    cd /workspace/cilium && \
    git checkout a2f97aa8d2de4bb360bee1e295e20556ce4166ce

WORKDIR /workspace/cilium
