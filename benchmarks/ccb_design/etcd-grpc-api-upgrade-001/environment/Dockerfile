FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    python3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /ccb_crossrepo/src

RUN git clone --depth 1 https://github.com/sg-evals/etcd--d89978e8.git /ccb_crossrepo/src/etcd
RUN git clone --depth 1 https://github.com/sg-evals/kubernetes--8c9c67c0.git /ccb_crossrepo/src/kubernetes
RUN git clone --depth 1 https://github.com/sg-evals/containerd--317286ac.git /ccb_crossrepo/src/containerd

RUN (adduser --disabled-password --gecos '' claude 2>/dev/null || true)

WORKDIR /workspace

RUN git init && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent" && \
    git config --global safe.directory '*'

RUN mkdir -p /logs/agent /logs/verifier && \
    chown -R claude:claude /workspace /logs /ccb_crossrepo

ENTRYPOINT []
