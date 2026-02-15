FROM rust:1.82-bookworm

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    python3-pip \
    npm

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone Rust compiler at pinned commit (1.93.1)
RUN git clone --filter=blob:none --no-checkout https://github.com/rust-lang/rust.git . && \
    git checkout 01f6ddf7588f42ae2d7eb0a2f21d44e8e96674cf && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Copy tests (verifier, ground truth)
COPY tests/ /workspace/tests/
