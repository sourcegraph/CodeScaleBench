FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install base dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    wget \
    git \
    ca-certificates \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Install Rust (to shared location for non-root user)
ENV RUSTUP_HOME=/usr/local/rustup
ENV CARGO_HOME=/usr/local/cargo
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path
ENV PATH="/usr/local/cargo/bin:${PATH}"

# Install Python 3 for verifier
RUN apt-get update && apt-get install -y python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Create working directories with world-writable permissions for session files
# This allows Harbor to read Claude Code session files regardless of user ownership
RUN mkdir -p /app /logs /workspace /tests /installed-agent &&     chmod 777 /logs /workspace /tests /installed-agent

# Copy project files
COPY project /app/project

# Install Node.js 22 and Claude Code globally
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - &&     apt-get install -y nodejs &&     npm install -g @anthropic-ai/claude-code@latest &&     rm -rf /var/lib/apt/lists/*

# Container runs as root - agent code will create 'claude' user at runtime
# and switch to it before running Claude Code
WORKDIR /app

CMD ["/bin/bash"]
