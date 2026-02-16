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

# Clone envoyproxy/go-control-plane at xdsmatcher/v0.14.0
RUN git clone --depth 1 https://github.com/envoyproxy/go-control-plane.git go-control-plane \
    && cd go-control-plane && git fetch --depth 1 origin 71637ad69bbc5f51fbb2562e612a4365292804a5 \
    && git checkout 71637ad69bbc5f51fbb2562e612a4365292804a5

# Clone istio/istio at 1.29.0
RUN git clone --depth 1 https://github.com/istio/istio.git istio \
    && cd istio && git fetch --depth 1 origin 2300e2458ab713c2c514a58da1ea8b03343ada7e \
    && git checkout 2300e2458ab713c2c514a58da1ea8b03343ada7e

# Clone emissary-ingress/emissary at v4.0.0-rc.1
RUN git clone --depth 1 https://github.com/emissary-ingress/emissary.git emissary \
    && cd emissary && git fetch --depth 1 origin 3bbdbe0fafcc9dd6b9f54935d34f6614afb49302 \
    && git checkout 3bbdbe0fafcc9dd6b9f54935d34f6614afb49302

RUN mkdir -p /logs/verifier /logs/agent

CMD ["/bin/bash"]
