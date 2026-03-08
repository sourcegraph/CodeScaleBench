FROM ubuntu:22.04

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    python3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Clone Terraform at v1.10.0 release (pinned SHA)
RUN git clone --depth 1 https://github.com/sg-evals/terraform--24236f4f.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
