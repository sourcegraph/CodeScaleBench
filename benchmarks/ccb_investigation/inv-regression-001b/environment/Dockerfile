FROM ubuntu:22.04

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    wget \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Go 1.23 (required for Prometheus 3.0)
RUN wget https://go.dev/dl/go1.23.4.linux-amd64.tar.gz && \
    tar -C /usr/local -xzf go1.23.4.linux-amd64.tar.gz && \
    rm go1.23.4.linux-amd64.tar.gz

ENV PATH="/usr/local/go/bin:${PATH}"
ENV GOPATH="/go"
ENV PATH="${GOPATH}/bin:${PATH}"

# Clone prometheus repo and check out commit AFTER regression, BEFORE fix
# Fix commit: e10bbf0a84d59a9f20144ed578c9afa7079dbacd (PR #15489, merged ~Nov 2024)
# We pin to e10bbf0a~1 (parent of fix) so the bug exists in the codebase
WORKDIR /workspace
RUN git clone --filter=blob:none --no-checkout https://github.com/prometheus/prometheus.git && \
    cd prometheus && \
    git checkout e10bbf0a84d59a9f20144ed578c9afa7079dbacd~1

WORKDIR /workspace/prometheus

# Create investigation output directory
RUN mkdir -p /logs/agent

CMD ["/bin/bash"]
