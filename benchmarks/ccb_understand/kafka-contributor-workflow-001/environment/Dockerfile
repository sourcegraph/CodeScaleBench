FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    git \
    openjdk-17-jdk \
    && rm -rf /var/lib/apt/lists/*

# Clone Kafka at the pinned version
RUN git clone https://github.com/apache/kafka.git /workspace && \
    cd /workspace && \
    git checkout 3.9.0

WORKDIR /workspace
