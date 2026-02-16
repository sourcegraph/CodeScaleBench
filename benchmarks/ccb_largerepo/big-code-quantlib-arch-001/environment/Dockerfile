FROM gcc:14-bookworm

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    python3-pip \
    npm \
    cmake \
    libboost-all-dev

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone QuantLib at pinned commit (v1.41)
RUN git clone --filter=blob:none --no-checkout https://github.com/lballabio/QuantLib.git . && \
    git checkout v1.41 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"
