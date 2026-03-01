FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install git and dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends git ca-certificates python3 && \
    rm -rf /var/lib/apt/lists/*

# Clone VS Code at pinned commit (v1.99.3)
RUN git clone --depth 1 https://github.com/sg-evals/vscode--17baf841.git /workspace/vscode

WORKDIR /workspace/vscode
