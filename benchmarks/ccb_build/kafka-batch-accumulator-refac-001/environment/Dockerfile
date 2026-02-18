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

# Clone Kafka at pinned commit (4.1.1)
RUN git clone --filter=blob:none --no-checkout https://github.com/apache/kafka.git . && \
    git checkout 0753c489afad403fb6e78fda4c4a380e46f500c0 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"
