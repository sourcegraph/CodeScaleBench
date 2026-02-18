FROM ubuntu:22.04

# Install git and basic tools
RUN apt-get update && apt-get install -y \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Clone Apache Kafka at a stable release tag (3.9.0 - latest stable as of Feb 2026)
RUN git clone --filter=blob:none --no-checkout https://github.com/apache/kafka.git . && \
    git checkout 3.9.0 && \
    git config user.email "agent@benchmark.local" && \
    git config user.name "Agent"

# Create logs directory for agent output
RUN mkdir -p /logs/agent

CMD ["/bin/bash"]
