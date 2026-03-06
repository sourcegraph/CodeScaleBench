FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates python3 curl \
    && rm -rf /var/lib/apt/lists/*

# Pre-create claude user
RUN (adduser --disabled-password --gecos '' claude 2>/dev/null || true)

# Clone repo as claude user
USER claude
WORKDIR /workspace
RUN git clone --depth 1 https://github.com/grpc/grpc.git . || \
    (git init && git config user.email "agent@example.com" && git config user.name "Agent")
USER root

RUN mkdir -p /logs/agent /logs/verifier && \
    chown -R claude:claude /logs

ENTRYPOINT []
