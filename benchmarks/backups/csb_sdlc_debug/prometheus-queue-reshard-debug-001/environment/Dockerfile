FROM golang:1.23-bookworm

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    python3 \
    && rm -rf /var/lib/apt/lists/*

# Clone Prometheus at the target commit (before remote-write resharding fix)
# Commit ba14bc4 is the broken change (deprecated per-QM counters);
# revert commit 6806b68 fixes it
RUN git clone --depth 1 https://github.com/sg-evals/prometheus--ba14bc4.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
