FROM ubuntu:22.04

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone Kubernetes at the target commit (before the NoExecute taint delay fix)
# PR #120816 (commit f718096) fixes the bug where processTaintBaseEviction()
# receives observedReadyCondition (stale) instead of currentReadyCondition,
# causing a one-cycle delay before NoExecute taint is applied to unreachable nodes.
# We check out the parent commit to get the broken state.
RUN git clone --filter=blob:none --no-checkout https://github.com/kubernetes/kubernetes.git . && \
    git checkout f718096~1 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
