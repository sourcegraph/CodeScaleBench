FROM ubuntu:22.04

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates python3 && \
    rm -rf /var/lib/apt/lists/*

# Install Node.js for Claude Code CLI
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# Create claude user and workspace (clone-as-claude pattern)
RUN adduser --disabled-password --gecos '' claude 2>/dev/null || true
RUN mkdir -p /workspace && chown claude:claude /workspace

# Clone terraform at pre-fix commit as claude user
USER claude
RUN git clone --depth 1 https://github.com/sg-evals/terraform--abd6b9ef.git /workspace
USER root

WORKDIR /workspace
ENTRYPOINT []
