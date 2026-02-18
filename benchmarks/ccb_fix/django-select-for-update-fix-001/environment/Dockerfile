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
    git checkout 9e7cc2b628fe8fd3895986af9b7fc9525034c1b0 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"
