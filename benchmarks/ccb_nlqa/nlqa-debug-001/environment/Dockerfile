FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install git and dependencies
RUN apt-get update && \
    apt-get install -y git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Clone VS Code at pinned commit (v1.99.3)
RUN git clone --filter=blob:none --no-checkout https://github.com/microsoft/vscode.git /workspace/vscode && \
    cd /workspace/vscode && \
    git checkout 17baf841131aa23349f217ca7c570c76ee87b957

WORKDIR /workspace/vscode
