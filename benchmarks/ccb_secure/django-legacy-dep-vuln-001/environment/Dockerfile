FROM python:3.11-slim

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone Django at pinned commit
RUN git clone --filter=blob:none --no-checkout https://github.com/django/django.git . && \
    git checkout 674eda1c03a3187905f48afee0f15226aa62fdf3 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"
