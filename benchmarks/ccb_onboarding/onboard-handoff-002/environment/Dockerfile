FROM ubuntu:22.04

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /workspace

# Clone Terraform repository at a stable release tag
# Using v1.9.0 (recent stable release with mature backend system)
RUN git clone --filter=blob:none --no-checkout https://github.com/hashicorp/terraform.git . \
    && git checkout v1.9.0

# Configure git for potential commits (if agent wants to take notes)
RUN git config user.email "agent@benchmark.local" \
    && git config user.name "Benchmark Agent"

# Ensure logs directory exists
RUN mkdir -p /logs/agent
