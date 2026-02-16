FROM ubuntu:22.04

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    golang-1.21 \
    build-essential \
    curl \
    vim \
    less \
    && rm -rf /var/lib/apt/lists/*

# Setup Go environment
ENV PATH="/usr/lib/go-1.21/bin:${PATH}"
ENV GOPATH="/root/go"
ENV PATH="${GOPATH}/bin:${PATH}"

WORKDIR /workspace

# Clone Prometheus repository and checkout to the regressing commit
# Commit a48a01836 (June 14, 2017) introduced the bug
# This is the parent of the fix commit e86d82ad2 (Nov 1, 2017)
RUN git clone --filter=blob:none --no-checkout https://github.com/prometheus/prometheus.git . && \
    git checkout a48a01836810055029145881b7777fddd00c233a && \
    git config user.email "agent@benchmark.local" && \
    git config user.name "Benchmark Agent"

# Note: This commit has the bug where loadGroups uses "name;file" as key
# but ApplyConfig uses only "name" as key, causing state loss on reload

WORKDIR /workspace
