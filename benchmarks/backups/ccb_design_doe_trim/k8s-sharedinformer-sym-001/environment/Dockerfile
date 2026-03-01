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

# Clone kubernetes/kubernetes at pinned SHA (2026-02-16)
RUN git clone --depth 1 https://github.com/sg-evals/kubernetes--31bf3ed4.git kubernetes

# Clone kubernetes/autoscaler at pinned SHA (2026-02-16)
RUN git clone --depth 1 https://github.com/sg-evals/autoscaler--0ccfef95.git autoscaler

RUN mkdir -p /logs/verifier /logs/agent

CMD ["/bin/bash"]
