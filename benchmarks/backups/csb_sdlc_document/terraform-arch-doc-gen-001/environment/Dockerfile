FROM ubuntu:22.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    python3 \
    python3-pip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /repo

# Clone Terraform repository (blobless clone for efficiency)
# Using commit a3dc571150a7651a1a4a8b302342d26089c97795 from main branch (2026-02-16)
RUN git clone --depth 1 https://github.com/sg-evals/terraform--a3dc5711.git .

# Checkout only the internal/ directory to save space and time
RUN git sparse-checkout init --cone \
    && git sparse-checkout set internal docs \
    && git checkout

WORKDIR /workspace
