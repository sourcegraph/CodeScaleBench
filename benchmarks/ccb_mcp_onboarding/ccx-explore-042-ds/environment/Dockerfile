FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Base tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    curl \
    python3 \
    python3-pip \
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
# Clone all fixture repos (baseline has full local access to every repo)
RUN git clone --depth 1 https://github.com/sg-evals/scikit-learn--1.6.1.git /workspace/scikit-learn
RUN git clone --depth 1 https://github.com/sg-evals/numpy--v2.2.2.git /workspace/numpy
RUN git clone --depth 1 https://github.com/sg-evals/pandas--v2.2.3.git /workspace/pandas
RUN git clone --depth 1 https://github.com/sg-evals/scipy--v1.15.1.git /workspace/scipy

# Initialize git identity for agent commits
RUN git config --global user.email "agent@example.com" && \
    git config --global user.name "Agent" && \
    git config --global safe.directory '*'

# Switch back to root for Harbor's runtime setup
USER root

ENTRYPOINT []
