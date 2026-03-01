FROM eclipse-temurin:17-jdk

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    curl \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN (adduser --disabled-password --gecos '' claude 2>/dev/null || true)

WORKDIR /workspace

USER claude
RUN git clone --depth 1 https://github.com/sg-evals/kafka--0753c489.git kafka && \
    git clone --depth 1 https://github.com/sg-evals/flink--0cc95fcc.git flink && \
    cd kafka && git config user.email "agent@example.com" && git config user.name "Agent" && \
    cd /workspace/flink && git config user.email "agent@example.com" && git config user.name "Agent"
USER root

RUN mkdir -p /logs/agent /logs/verifier && \
    chown -R claude:claude /logs

ENTRYPOINT []
