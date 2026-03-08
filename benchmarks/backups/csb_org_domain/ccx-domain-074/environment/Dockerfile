FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Base tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    curl \
    python3 \
    g++ make \
    && rm -rf /var/lib/apt/lists/*

# Create claude user BEFORE cloning so files are owned correctly from the
# start.  This avoids a post-clone chown -R layer that doubles image size
# and takes 15-30 min on overlay2 (copy-on-write duplicates every inode).
RUN adduser --disabled-password --gecos '' claude 2>/dev/null || true
RUN mkdir -p /workspace /logs/agent /logs/verifier && \
    chown -R claude:claude /workspace /logs

# Clone as claude — files land claude-owned, no separate chown layer needed.
USER claude
WORKDIR /workspace
# Clone local checkout repos (baseline config: agent has local access to these)
RUN git clone --depth 1 https://github.com/sg-evals/envoy--v1.31.2 /workspace/envoy--v1.31.2
RUN git clone --depth 1 https://github.com/sg-evals/data-plane-api--84e84367 /workspace/data-plane-api--84e84367
RUN git clone --depth 1 https://github.com/sg-evals/go-control-plane--71637ad6 /workspace/go-control-plane--71637ad6
RUN git clone --depth 1 https://github.com/sg-evals/grpc--957dba5e /workspace/grpc--957dba5e

# Initialize git identity for agent commits
RUN git config --global user.email "agent@example.com" && \
    git config --global user.name "Agent" && \
    git config --global safe.directory '*'

# Switch back to root for Harbor's runtime setup
USER root

ENTRYPOINT []
