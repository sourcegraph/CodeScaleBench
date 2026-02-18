FROM gcc:13

WORKDIR /workspace

# Install dependencies including curl for Node.js setup
RUN apt-get update && apt-get install -y cmake ninja-build git curl

# Install Node.js for Claude Code CLI
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone PyTorch repository at task-specific commit (no submodules needed)
RUN git clone --no-checkout https://github.com/pytorch/pytorch.git /workspace && \
    cd /workspace && \
    git checkout cbe1a35dbdfdc9b7490212bdd812f3e2f4ce9e2d

# Pre-create claude user and fix ownership so Harbor agent setup is instant
RUN (adduser --disabled-password --gecos '' claude 2>/dev/null || adduser -D -s /bin/bash claude 2>/dev/null || true) && \
    chown -R claude:claude /workspace
