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

# Clone hashicorp/terraform at v1.15.0-alpha20260204
RUN git clone --depth 1 https://github.com/hashicorp/terraform.git terraform \
    && cd terraform && git fetch --depth 1 origin f65c52c8995a627e64c82827c75edf99a9399e4b \
    && git checkout f65c52c8995a627e64c82827c75edf99a9399e4b

# Clone hashicorp/terraform-provider-aws at v6.32.1
RUN git clone --depth 1 https://github.com/hashicorp/terraform-provider-aws.git terraform-provider-aws \
    && cd terraform-provider-aws && git fetch --depth 1 origin e9b4629e752e76551c7bca0f317e98e43bc96a7c \
    && git checkout e9b4629e752e76551c7bca0f317e98e43bc96a7c

RUN mkdir -p /logs/verifier /logs/agent

CMD ["/bin/bash"]
