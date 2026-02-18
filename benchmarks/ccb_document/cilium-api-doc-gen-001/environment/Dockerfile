FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Clone Cilium at specific commit (main 2026-02-16)
RUN git clone --filter=blob:none --no-checkout https://github.com/cilium/cilium.git repo && \
    cd repo && \
    git checkout ad6b298dbdcb9b828a247c54a477a9cfa43eff00 && \
    git sparse-checkout init --cone && \
    git sparse-checkout set pkg/bpf pkg/maps pkg/datapath/maps && \
    git checkout

# Agent writes documentation.md to /workspace/
# Verifier: /tests/test.sh scores against /tests/ground_truth.json
