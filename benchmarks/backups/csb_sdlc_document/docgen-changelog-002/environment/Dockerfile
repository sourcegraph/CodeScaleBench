FROM golang:1.22-bookworm

WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    python3 \
    ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/sg-evals/flipt--3d5a345f.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

RUN mkdir -p /app
