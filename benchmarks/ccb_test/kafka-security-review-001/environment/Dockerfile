FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    openjdk-17-jdk \
    python3 \
    python3-pip \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Clone Kafka at pinned tag 3.8.0
RUN git clone --branch 3.8.0 --depth 1 https://github.com/apache/kafka.git . \
    && git config --global user.email "test@example.com" \
    && git config --global user.name "Test User"

# Inject defects
COPY inject_defects.sh /tmp/inject_defects.sh
RUN chmod +x /tmp/inject_defects.sh && /tmp/inject_defects.sh

# Set Java home
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

CMD ["/bin/bash"]
