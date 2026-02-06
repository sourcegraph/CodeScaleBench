FROM ubuntu:22.04

# Install common tools
RUN apt-get update && apt-get install -y \
    git \
    curl \
    ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (for Claude Code CLI)
RUN if ! command -v node &> /dev/null; then \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs; \
    fi

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone repo at pinned commit
RUN git clone --filter=blob:none https://github.com/agentic-review-benchmarks/benchmark-pr-mapping.git /workspace && \
    cd /workspace && \
    git checkout 5f6c30d18fbf5c310513eca7f4e160ccb0e0e668

# Create directories
RUN mkdir -p /workspace/tests /logs/verifier

# Copy test files
COPY tests/ /workspace/tests/
RUN chmod +x /workspace/tests/test.sh

WORKDIR /workspace
