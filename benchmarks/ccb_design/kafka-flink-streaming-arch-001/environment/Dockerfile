# kafka-flink-streaming-arch-001 — multi-repo baseline
# Uses pre-built ccb-repo images to avoid git clone during Docker build.
FROM ccb-repo-kafka-0753c489 AS kafka-src
FROM ccb-repo-flink-0cc95fcc AS flink-src

FROM eclipse-temurin:17-jdk

WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=kafka-src /workspace /workspace/kafka
COPY --from=flink-src /workspace /workspace/flink

RUN cd /workspace/kafka && git config user.email "agent@example.com" && git config user.name "Agent" && \
    cd /workspace/flink && git config user.email "agent@example.com" && git config user.name "Agent"
