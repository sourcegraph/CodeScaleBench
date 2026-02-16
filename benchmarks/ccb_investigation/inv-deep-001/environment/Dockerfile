FROM ubuntu:22.04

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    && rm -rf /var/lib/apt/lists/*

# Clone Envoy at the target commit (before router header mutation fix)
# PR #40856 (commit 25f893b) fixes the bug where response_headers_to_add
# is processed multiple times for local responses due to double
# finalizeResponseHeaders() call. We check out the parent to get the broken state.
# The bug was introduced by PR #39534 which moved finalizeResponseHeaders()
# into the modify_headers_ callback, causing double processing on local replies.
RUN git clone --filter=blob:none --no-checkout https://github.com/envoyproxy/envoy.git . && \
    git checkout 25f893b~1 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
