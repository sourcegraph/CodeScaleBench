FROM rust:bookworm

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    python3-pip \
    npm \
    build-essential \
    autoconf \
    pkg-config

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone the actual Servo repository
# This ensures BOTH baseline and MCP agents have identical file access
# Note: Servo is a large Rust codebase (~1.6GB)
RUN git clone --depth 1 https://github.com/servo/servo.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Task setup complete
# Note: Both baseline and MCP agents now have access to the real Servo source.
# Baseline will use local grep/find/rg. MCP will use Sourcegraph semantic search.
