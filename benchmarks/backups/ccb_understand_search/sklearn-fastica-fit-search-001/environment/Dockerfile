FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN (adduser --disabled-password --gecos '' claude 2>/dev/null || true)

RUN mkdir -p /workspace && chown claude:claude /workspace

USER claude
WORKDIR /workspace
RUN git clone --depth 1 https://github.com/sg-evals/scikit-learn--cb7e82dd.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"
USER root

RUN mkdir -p /logs/agent /logs/verifier && \
    chown -R claude:claude /logs

ENTRYPOINT []
