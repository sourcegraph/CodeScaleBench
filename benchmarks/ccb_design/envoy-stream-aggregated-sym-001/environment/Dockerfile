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

# Clone envoyproxy/envoy at pinned SHA (2026-02-16)
RUN git clone --depth 1 https://github.com/envoyproxy/envoy.git envoy \
    && cd envoy && git fetch --depth 1 origin 1d0ba73ad200d28e86c0c23f76c55320f82a8fba \
    && git checkout 1d0ba73ad200d28e86c0c23f76c55320f82a8fba

# Clone grpc/grpc-go at pinned SHA (2026-02-16)
RUN git clone --depth 1 https://github.com/grpc/grpc-go.git grpc-go \
    && cd grpc-go && git fetch --depth 1 origin 3be7e2d0be702e0ca93d95db50abb9381b91e409 \
    && git checkout 3be7e2d0be702e0ca93d95db50abb9381b91e409

RUN mkdir -p /logs/verifier /logs/agent

CMD ["/bin/bash"]
