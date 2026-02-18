FROM ubuntu:22.04

# Install prerequisites
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Clone apache/kafka at pinned release tag 4.1.1
RUN git clone --filter=blob:none --no-checkout https://github.com/apache/kafka.git /workspace && \
    cd /workspace && \
    git checkout 0753c489afad403fb6e78fda4c4a380e46f500c0

WORKDIR /workspace
