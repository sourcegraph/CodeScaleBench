FROM ubuntu:22.04

# Install minimal dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Clone Terraform at two pinned versions via sg-evals mirrors
RUN git clone --depth 1 https://github.com/sg-evals/terraform--7637a921.git terraform-v1.9.0 && \
    git clone --depth 1 https://github.com/sg-evals/terraform--24236f4f.git terraform-v1.10.0

# Verify worktrees exist
RUN test -d /workspace/terraform-v1.9.0 && \
    test -d /workspace/terraform-v1.10.0 && \
    echo "Both Terraform worktrees created successfully"

# Set working directory
WORKDIR /workspace
