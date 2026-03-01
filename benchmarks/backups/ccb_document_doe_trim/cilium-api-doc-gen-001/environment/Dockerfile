FROM ubuntu:22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    python3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Clone Cilium at specific commit (main 2026-02-16)
RUN git clone --depth 1 https://github.com/sg-evals/cilium--ad6b298d.git repo

# Agent writes documentation.md to /workspace/
# Verifier: /tests/test.sh scores against /tests/ground_truth.json
