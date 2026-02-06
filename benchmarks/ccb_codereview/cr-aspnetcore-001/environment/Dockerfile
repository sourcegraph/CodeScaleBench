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

# Clone dotnet/aspnetcore at pinned commit (PR #64636 merge commit)
RUN git clone --filter=blob:none --no-checkout https://github.com/dotnet/aspnetcore.git /workspace && \
    cd /workspace && \
    git checkout 875255737993775850f1f3650c10ddb43ef00ced && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Inject defects into the codebase
COPY inject_defects.sh /tmp/inject_defects.sh
RUN chmod +x /tmp/inject_defects.sh && /tmp/inject_defects.sh && rm /tmp/inject_defects.sh

# Create directories for verifier (tests uploaded at runtime by Harbor verifier)
RUN mkdir -p /workspace/tests /logs/verifier

WORKDIR /workspace
