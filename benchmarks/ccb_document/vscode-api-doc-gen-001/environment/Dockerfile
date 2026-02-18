FROM ubuntu:22.04

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Clone VS Code repository with blobless clone for faster setup
# Commit 69d110f2 is from main branch (2026-02-16)
RUN git clone --filter=blob:none --no-checkout https://github.com/microsoft/vscode.git repo \
    && cd repo \
    && git checkout 69d110f2fe9decdf0b4f79f894f23b3c1967bcb2 \
    && git sparse-checkout init --cone \
    && git sparse-checkout set src/vs/vscode.d.ts src/vs/workbench extensions \
    && git checkout

# Set working directory to repo root so agent can explore the codebase
WORKDIR /workspace/repo

# Entry point: agent will generate documentation.md in /workspace/
CMD ["/bin/bash"]
