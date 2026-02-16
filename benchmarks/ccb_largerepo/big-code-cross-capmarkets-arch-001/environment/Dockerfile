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

# Clone Apache Kafka at pinned tag (4.1.1) into /workspace/kafka/
RUN git clone --filter=blob:none --no-checkout https://github.com/apache/kafka.git /workspace/kafka && \
    cd /workspace/kafka && \
    git checkout 4.1.1 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Clone Apache Flink at pinned branch (release-2.2.0) into /workspace/flink/
RUN git clone --filter=blob:none --no-checkout https://github.com/apache/flink.git /workspace/flink && \
    cd /workspace/flink && \
    git checkout release-2.2.0 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Copy tests (verifier, ground truth)
COPY tests/ /workspace/tests/
