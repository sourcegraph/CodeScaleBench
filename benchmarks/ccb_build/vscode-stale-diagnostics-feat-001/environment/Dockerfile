FROM node:22-bookworm

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    build-essential \
    python3 \
    python3-pip

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone the actual VS Code repository at pinned commit (1.96.0)
# This ensures BOTH baseline and MCP agents have identical file access
RUN git clone --filter=blob:none --no-checkout https://github.com/microsoft/vscode.git . && \
    git checkout 138f619c86f1199955d53b4166bef66ef252935c && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Install VS Code dependencies (required for testing)
RUN npm install --legacy-peer-deps 2>&1 | tail -10 || true

# Task setup complete
# Note: Both baseline and MCP agents now have access to the real VS Code source.
# Baseline will use local grep/find/rg. MCP will use Sourcegraph semantic search.
