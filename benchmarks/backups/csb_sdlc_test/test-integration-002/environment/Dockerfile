FROM golang:1.22-bookworm

WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    python3 \
    ripgrep \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/sg-evals/navidrome--9c3b4561.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

RUN mkdir -p /workspace/scanner /workspace/testdata /app
