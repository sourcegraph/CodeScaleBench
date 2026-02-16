FROM ubuntu:22.04

WORKDIR /workspace

# Install dependencies including Java for Kafka
RUN apt-get update && apt-get install -y \
    git \
    curl \
    python3 \
    openjdk-11-jdk \
    && rm -rf /var/lib/apt/lists/*

# Clone Kafka at the target commit (before the cooperative rebalance offset commit fix)
# PR #12349 (commit d8541b20a106f22736947e0c2f293833f3c3873b) fixes KAFKA-14024, where
# the consumer's onJoinPrepare callback keeps initiating new async offset commits
# during each poll() because the completion flag is never updated, causing the consumer
# to be kicked out of the group after rebalance timeout.
# We check out the parent commit to get the broken state.
RUN git clone --filter=blob:none --no-checkout https://github.com/apache/kafka.git . && \
    git checkout d8541b20a106f22736947e0c2f293833f3c3873b~1 && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
