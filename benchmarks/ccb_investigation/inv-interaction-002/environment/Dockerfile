FROM ubuntu:22.04

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    && rm -rf /var/lib/apt/lists/*

# Clone Cilium at the target commit (before the identity/SelectorCache race fix)
# PR #42049 (commit 696017a) fixes the race condition where identity allocation
# completes and triggers endpoint regeneration before the SelectorCache has
# processed identity update events, causing incomplete policy calculations.
# We check out the parent commit to get the broken state.
RUN git clone --filter=blob:none --no-checkout https://github.com/cilium/cilium.git . && \
    git checkout 1ded914d065922fe624c0607e44189d0fbb3121c && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
