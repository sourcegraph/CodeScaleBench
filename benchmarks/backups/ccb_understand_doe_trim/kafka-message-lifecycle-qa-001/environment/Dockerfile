FROM ubuntu:22.04

# Install prerequisites
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Clone apache/kafka at pinned release tag 4.1.1
RUN git clone --depth 1 https://github.com/sg-evals/kafka--0753c489.git /workspace

WORKDIR /workspace
