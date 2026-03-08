FROM debian:bookworm-slim

WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    python3 \
    build-essential \
    jq \
    bc \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/sg-evals/curl--09e25b9d.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"
