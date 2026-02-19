FROM gcc:14-bookworm

WORKDIR /workspace

# Install dependencies (libboost-dev = headers only; avoids MPI/gfortran conflicts on gcc:14)
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    python3-pip \
    npm \
    cmake \
    libboost-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone QuantLib at pinned commit (v1.41)
RUN git clone --filter=blob:none --no-checkout https://github.com/lballabio/QuantLib.git . && \
    git checkout dbdcc14e3ddda93d49ee8df76302f26843b3f34e && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"
