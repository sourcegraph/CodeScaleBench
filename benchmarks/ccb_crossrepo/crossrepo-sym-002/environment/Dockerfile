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

# Clone kubernetes/kubernetes at pinned SHA (2026-02-16)
RUN git clone --depth 1 https://github.com/kubernetes/kubernetes.git kubernetes \
    && cd kubernetes && git fetch --depth 1 origin 31bf3ed48b91b67e5003d8df1b3bd0b918d1fb94 \
    && git checkout 31bf3ed48b91b67e5003d8df1b3bd0b918d1fb94

# Clone kubernetes/autoscaler at pinned SHA (2026-02-16)
RUN git clone --depth 1 https://github.com/kubernetes/autoscaler.git autoscaler \
    && cd autoscaler && git fetch --depth 1 origin 0ccfef950b110898dc41351edaef7822df060b48 \
    && git checkout 0ccfef950b110898dc41351edaef7822df060b48

RUN mkdir -p /logs/verifier /logs/agent

CMD ["/bin/bash"]
