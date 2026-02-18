FROM eclipse-temurin:21-jdk

WORKDIR /workspace

RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    npm \
    ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

RUN git clone --filter=blob:none --no-checkout https://github.com/apache/kafka.git . && \
    git checkout e678b4b && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

RUN mkdir -p /app
