FROM eclipse-temurin:17-jdk

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    python3-pip \
    npm \
    maven

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone Strata at pinned commit (v2.12.65)
RUN git clone --filter=blob:none --no-checkout https://github.com/OpenGamma/Strata.git . && \
    git checkout v2.12.65 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"
