FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Base tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    curl \
    python3 \
    cargo \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Clone local checkout repos (baseline config: agent has local access to these)
RUN git clone --depth 1 --branch 01f6ddf7 https://github.com/sg-evals/rust--01f6ddf7 /workspace/rust--01f6ddf7
RUN git clone --depth 1 --branch be6a2f99 https://github.com/sg-evals/servo--be6a2f99 /workspace/servo--be6a2f99

# Initialize git identity for agent commits
RUN git config --global user.email "agent@example.com" && \
    git config --global user.name "Agent" && \
    git config --global safe.directory '*'

# Create log directories
RUN mkdir -p /logs/agent /logs/verifier

ENTRYPOINT []
