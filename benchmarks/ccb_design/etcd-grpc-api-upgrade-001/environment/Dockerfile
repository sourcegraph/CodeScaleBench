# etcd-grpc-api-upgrade-001 — multi-repo baseline
# Repos cloned into /ccb_crossrepo/src/ to match verifier expectations.
FROM ccb-repo-etcd-d89978e8 AS etcd-src
FROM ccb-repo-k8s-8c9c67c0 AS k8s-src
FROM ccb-repo-containerd-317286ac AS containerd-src

FROM golang:1.23-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    python3 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /ccb_crossrepo/src
COPY --from=etcd-src /workspace /ccb_crossrepo/src/etcd
COPY --from=k8s-src /workspace /ccb_crossrepo/src/kubernetes
COPY --from=containerd-src /workspace /ccb_crossrepo/src/containerd

WORKDIR /workspace

RUN git init && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent" && \
    git config --global safe.directory '*'
