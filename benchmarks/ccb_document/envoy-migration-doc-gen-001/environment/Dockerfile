FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    git \
    python3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Clone Envoy repo with blob filtering for fast clone
RUN git clone --filter=blob:none --no-checkout https://github.com/envoyproxy/envoy.git envoy-repo

# Create worktrees for v1.30.0 and v1.31.0
WORKDIR /workspace/envoy-repo
RUN git worktree add ../envoy-v1.30 50ea83e602d5da162df89fd5798301e22f5540cf
RUN git worktree add ../envoy-v1.31 7b8baff1758f0a584dcc3cb657b5032000bcb3d7

# Keep main clone (worktrees reference its .git directory)
# Set working directory to workspace root
WORKDIR /workspace
