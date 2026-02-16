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

# Clone envoyproxy/go-control-plane at pinned SHA (2026-02-16)
RUN git clone --depth 1 https://github.com/envoyproxy/go-control-plane.git go-control-plane \
    && cd go-control-plane && git fetch --depth 1 origin 0b8a46e8b5e5e8c5d9a7f4b3c2e1a8d9f6c7e5a4 \
    && git checkout 0b8a46e8b5e5e8c5d9a7f4b3c2e1a8d9f6c7e5a4

# Clone istio/istio at pinned SHA (2026-02-16)
RUN git clone --depth 1 https://github.com/istio/istio.git istio \
    && cd istio && git fetch --depth 1 origin 7f8c6b5a4d3e2c1b9a8f7e6d5c4b3a2e1d0c9b8a \
    && git checkout 7f8c6b5a4d3e2c1b9a8f7e6d5c4b3a2e1d0c9b8a

# Clone emissary-ingress/emissary at pinned SHA (2026-02-16)
RUN git clone --depth 1 https://github.com/emissary-ingress/emissary.git emissary \
    && cd emissary && git fetch --depth 1 origin 3e5a9c8b7d6f4a2e1c0b9a8d7f6e5c4b3a2d1e0f \
    && git checkout 3e5a9c8b7d6f4a2e1c0b9a8d7f6e5c4b3a2d1e0f

RUN mkdir -p /logs/verifier /logs/agent

CMD ["/bin/bash"]
