FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -qq && apt-get install -y -qq \
    git \
    curl \
    ca-certificates \
    python3 \
    python3-pip \
    jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Clone kubernetes/api at pinned SHA (2026-02-16)
RUN git clone --depth 1 https://github.com/kubernetes/api.git api \
    && cd api && git fetch --depth 1 origin c4a8a38b3ae0f0f8d6c8e0b3f7d9c8e8f9e0c8d7 \
    && git checkout c4a8a38b3ae0f0f8d6c8e0b3f7d9c8e8f9e0c8d7

# Clone kubernetes/apimachinery at pinned SHA (2026-02-16)
RUN git clone --depth 1 https://github.com/kubernetes/apimachinery.git apimachinery \
    && cd apimachinery && git fetch --depth 1 origin a8e3f1c7b9d2e4f6a8b0c9d7e5f3a1b8c6d4e2f0 \
    && git checkout a8e3f1c7b9d2e4f6a8b0c9d7e5f3a1b8c6d4e2f0

RUN mkdir -p /logs/verifier /logs/agent

CMD ["/bin/bash"]
