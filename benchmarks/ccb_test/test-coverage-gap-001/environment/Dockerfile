FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    python3 \
    ripgrep \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN (adduser --disabled-password --gecos '' claude 2>/dev/null || true)

USER claude
WORKDIR /workspace
RUN git clone --depth 1 https://github.com/sg-evals/envoy--1d0ba73a.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"
USER root

RUN mkdir -p /logs/agent /logs/verifier && \
    chown -R claude:claude /logs

ENTRYPOINT []
