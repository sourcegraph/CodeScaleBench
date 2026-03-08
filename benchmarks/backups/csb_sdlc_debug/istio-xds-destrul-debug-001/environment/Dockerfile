FROM ubuntu:22.04

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    python3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Clone Istio at the pre-fix commit for the DestinationRule dependency bug.
# PR #38088 (merge commit 9fcfe231) fixes the bug where merged DestinationRules
# lose the metadata of contributing DRs, causing xDS pushes to be silently
# skipped when a non-surviving DR is updated.
# We check out the parent commit (f8c9b973) to get the broken state.
RUN git clone --depth 1 https://github.com/sg-evals/istio--f8c9b973.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
