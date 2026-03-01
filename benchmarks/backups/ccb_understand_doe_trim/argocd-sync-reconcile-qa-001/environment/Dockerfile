FROM ubuntu:22.04

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    python3 \
    && rm -rf /var/lib/apt/lists/*

# Clone Argo CD repository at v2.14.21
WORKDIR /workspace
RUN git clone --depth 1 https://github.com/sg-evals/argo-cd--206a6eec.git .

# Set git config for potential commits (not needed for Q&A but follows convention)
RUN git config --global user.email "agent@codecontextbench.dev" && \
    git config --global user.name "CCB Agent"

# Workspace is ready for investigation
WORKDIR /workspace
