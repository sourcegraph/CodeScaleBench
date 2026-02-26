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
RUN git clone --depth 1 https://github.com/sg-evals/llvm-project--a8f3c97d /workspace/llvm-project--a8f3c97d
RUN git clone --depth 1 https://github.com/sg-evals/gcc--96dfb333 /workspace/gcc--96dfb333

# Initialize git identity for agent commits
RUN git config --global user.email "agent@example.com" && \
    git config --global user.name "Agent" && \
    git config --global safe.directory '*'

# Switch back to root for Harbor's runtime setup
USER root

ENTRYPOINT []
