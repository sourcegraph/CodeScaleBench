FROM ubuntu:22.04

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Clone Argo CD repository at v2.14.21
WORKDIR /workspace
RUN git clone --filter=blob:none --no-checkout https://github.com/argoproj/argo-cd.git . && \
    git checkout 206a6eeca509bbf7f239301f3d3fa498c23251a4

# Set git config for potential commits (not needed for Q&A but follows convention)
RUN git config --global user.email "agent@codecontextbench.dev" && \
    git config --global user.name "CCB Agent"

# Workspace is ready for investigation
WORKDIR /workspace
