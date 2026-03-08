FROM golang:1.23-bookworm

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    python3 \
    && rm -rf /var/lib/apt/lists/*

# Clone Grafana at the target commit (v38 migration regression)
# Commit 26d36ec contains the migration fix; this mirror is pinned to its parent (8449a2e4)
RUN git clone --depth 1 https://github.com/sg-evals/grafana--8449a2e4.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
