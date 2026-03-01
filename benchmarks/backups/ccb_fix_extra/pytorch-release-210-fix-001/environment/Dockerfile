FROM gcc:13

WORKDIR /workspace

# Install dependencies including curl for Node.js setup
RUN apt-get update && apt-get install -y --no-install-recommends cmake ninja-build git curl

# Install Node.js for Claude Code CLI
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Clone PyTorch repository at task-specific commit (no submodules needed)
RUN git clone --depth 1 https://github.com/sg-evals/pytorch--863edc78.git /workspace

# Pre-create claude user and fix ownership so Harbor agent setup is instant
RUN (adduser --disabled-password --gecos '' claude 2>/dev/null || adduser -D -s /bin/bash claude 2>/dev/null || true) && \
    chown -R claude:claude /workspace
