FROM python:3.12-bookworm

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    npm

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone Django at pinned commit (5.2)
RUN git clone --filter=blob:none --no-checkout https://github.com/django/django.git . && \
    git checkout 5.2 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"
