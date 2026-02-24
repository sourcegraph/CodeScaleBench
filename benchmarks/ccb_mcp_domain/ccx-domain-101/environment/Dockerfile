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

WORKDIR /workspace

# Clone local checkout repos (baseline config: agent has local access to these)
RUN git clone --depth 1 --branch a8f3c97d3aa4943d03f657c8b086dbca4b6b50dd https://github.com/sg-evals/llvm-project--a8f3c97d /workspace/llvm-project--a8f3c97d
RUN git clone --depth 1 --branch 96dfb33390d0cd8b2cf35be83f0859930980e4b4 https://github.com/sg-evals/gcc--96dfb333 /workspace/gcc--96dfb333

# Initialize git identity for agent commits
RUN git config --global user.email "agent@example.com" && \
    git config --global user.name "Agent" && \
    git config --global safe.directory '*'

# Create log directories
RUN mkdir -p /logs/agent /logs/verifier

ENTRYPOINT []
