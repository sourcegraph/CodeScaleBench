FROM eclipse-temurin:17-jdk

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    python3-pip \
    npm

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone Apache Flink at pinned commit (release-2.2.0)
RUN git clone --filter=blob:none --no-checkout https://github.com/apache/flink.git . && \
    git checkout release-2.2.0 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"
