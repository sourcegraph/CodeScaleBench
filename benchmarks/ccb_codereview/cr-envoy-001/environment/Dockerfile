FROM ubuntu:22.04

# Install common tools (python3 needed for inject_defects.sh)
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (for Claude Code CLI)
RUN if ! command -v node &> /dev/null; then \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs; \
    fi

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone envoyproxy/envoy at pinned v1.33.0 tag (sparse checkout for relevant files)
RUN git clone --filter=blob:none --no-checkout https://github.com/envoyproxy/envoy.git /workspace && \
    cd /workspace && \
    git checkout v1.33.0 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Inject defects into the codebase
COPY inject_defects.sh /tmp/inject_defects.sh
RUN chmod +x /tmp/inject_defects.sh && /tmp/inject_defects.sh && rm /tmp/inject_defects.sh

# Create directories for verifier (tests uploaded at runtime by Harbor verifier)
RUN mkdir -p /workspace/tests /logs/verifier

WORKDIR /workspace
