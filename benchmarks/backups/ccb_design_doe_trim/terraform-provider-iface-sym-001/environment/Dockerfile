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

# Clone hashicorp/terraform at v1.15.0-alpha20260204
RUN git clone --depth 1 https://github.com/sg-evals/terraform--f65c52c8.git terraform

# Clone hashicorp/terraform-provider-aws at v6.32.1
RUN git clone --depth 1 https://github.com/sg-evals/terraform-provider-aws--e9b4629e.git terraform-provider-aws

RUN mkdir -p /logs/verifier /logs/agent

CMD ["/bin/bash"]
