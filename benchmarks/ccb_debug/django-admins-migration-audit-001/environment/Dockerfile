FROM python:3.12-bookworm

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone Django at the commit just before the ADMINS/MANAGERS migration
# Commit e295033 is the migration commit; we check out its parent
RUN git clone --filter=blob:none --no-checkout https://github.com/django/django.git . && \
    git checkout e295033~1 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
