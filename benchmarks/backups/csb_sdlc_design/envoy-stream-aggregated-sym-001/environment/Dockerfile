FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
    git \
    curl \
    ca-certificates \
    python3 \
    python3-pip \
    jq \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Clone envoyproxy/envoy at pinned SHA (2026-02-16)
RUN git clone --depth 1 https://github.com/sg-evals/envoy--1d0ba73a.git envoy

# Clone grpc/grpc-go at pinned SHA (2026-02-16)
RUN git clone --depth 1 https://github.com/sg-evals/grpc-go--3be7e2d0.git grpc-go

RUN mkdir -p /logs/verifier /logs/agent

CMD ["/bin/bash"]
