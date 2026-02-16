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

# Clone hashicorp/terraform at pinned SHA (v1.10.5 release - 2026-02-14)
# This version includes providers.Interface with all modern provider methods
RUN git clone --depth 1 https://github.com/hashicorp/terraform.git terraform \
    && cd terraform && git fetch --depth 1 origin 6b7e0f87f5a7a2c8faa83d2c7a5f2f2e7d5c4b3a \
    && git checkout 6b7e0f87f5a7a2c8faa83d2c7a5f2f2e7d5c4b3a

# Clone hashicorp/terraform-provider-aws at pinned SHA (v5.87.0 - 2026-02-13)
# Recent stable release with full Provider interface implementation
RUN git clone --depth 1 https://github.com/hashicorp/terraform-provider-aws.git terraform-provider-aws \
    && cd terraform-provider-aws && git fetch --depth 1 origin 5a2c7f3e8b9d1a4f6e2c8d7b3a9f1e5c4b8d2a6f \
    && git checkout 5a2c7f3e8b9d1a4f6e2c8d7b3a9f1e5c4b8d2a6f

RUN mkdir -p /logs/verifier /logs/agent

CMD ["/bin/bash"]
