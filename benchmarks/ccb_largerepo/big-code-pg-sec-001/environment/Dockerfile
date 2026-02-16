FROM gcc:14-bookworm

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    python3-pip \
    npm \
    bison \
    flex \
    libreadline-dev \
    zlib1g-dev

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone PostgreSQL at pinned commit (REL_18_2)
RUN git clone --filter=blob:none --no-checkout https://github.com/postgres/postgres.git . && \
    git checkout REL_18_2 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"
