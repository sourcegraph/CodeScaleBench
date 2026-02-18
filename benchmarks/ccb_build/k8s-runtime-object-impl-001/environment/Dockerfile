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

# Clone kubernetes/api (same pinned SHA as crossrepo-chain-001)
RUN git clone --depth 1 https://github.com/kubernetes/api.git api \
    && cd api && git fetch --depth 1 origin f32ed1d60cf0787a512bebd6c06a4b84ae0b7cc7 \
    && git checkout f32ed1d60cf0787a512bebd6c06a4b84ae0b7cc7

# Clone kubernetes/apimachinery (same pinned SHA as crossrepo-chain-001)
RUN git clone --depth 1 https://github.com/kubernetes/apimachinery.git apimachinery \
    && cd apimachinery && git fetch --depth 1 origin b2e9f88ff6d4c50c13061a53b1239c7707354eda \
    && git checkout b2e9f88ff6d4c50c13061a53b1239c7707354eda

RUN mkdir -p /logs/verifier /logs/agent

CMD ["/bin/bash"]
