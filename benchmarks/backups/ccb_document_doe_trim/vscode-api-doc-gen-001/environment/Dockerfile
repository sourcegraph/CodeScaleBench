FROM ubuntu:22.04

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Clone VS Code repository with blobless clone for faster setup
# Commit 69d110f2 is from main branch (2026-02-16)
RUN git clone --depth 1 https://github.com/sg-evals/vscode--69d110f2.git repo

# Set working directory to repo root so agent can explore the codebase
WORKDIR /workspace/repo

# Entry point: agent will generate documentation.md in /workspace/
CMD ["/bin/bash"]
