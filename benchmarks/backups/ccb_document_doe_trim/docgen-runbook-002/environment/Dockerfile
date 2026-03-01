FROM ubuntu:22.04

WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    python3 \
    ripgrep \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/sg-evals/envoy--1d0ba73a.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"
