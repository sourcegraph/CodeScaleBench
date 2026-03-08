FROM golang:1.20-bookworm

# Install dependencies for verifier (jq and bc for weighted checklist scoring)
RUN apt-get update && apt-get install -y --no-install-recommends jq bc git && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Clone grpcurl at v1.8.7 (the consuming project)
# Commit: 25c896aa59ffc36f7d12cf5d6c18e9c8f4421bfa
RUN git clone --depth 1 https://github.com/sg-evals/grpcurl--25c896aa.git grpcurl

# Clone grpc-go at v1.56.2 (the intermediate dependency)
# This version uses golang.org/x/net v0.14.0 (vulnerable to CVE-2023-39325)
RUN git clone --depth 1 https://github.com/sg-evals/grpc-go--v1.56.2.git grpc-go

# Clone golang.org/x/net at v0.14.0 (VULNERABLE version)
# This version is before v0.17.0 which fixed CVE-2023-39325
RUN git clone https://go.googlesource.com/net && \
    cd net && \
    git checkout v0.14.0 && \
    git describe --tags | grep -q "v0.14.0"

# Verify the vulnerability exists in x/net v0.14.0
# CVE-2023-39325 was fixed in v0.17.0 with addition of scheduleHandler() and handler throttling
# In v0.14.0, processHeaders() directly spawns handlers without limit enforcement
RUN cd net && \
    grep -q "func (sc \*serverConn) processHeaders" http2/server.go && \
    ! grep -q "scheduleHandler" http2/server.go && \
    echo "Confirmed: x/net v0.14.0 is VULNERABLE to CVE-2023-39325 (no scheduleHandler throttling)"

# Create logs directory for agent output
RUN mkdir -p /logs/agent

# Display dependency information
RUN echo "===== Repository Versions =====" && \
    echo "grpcurl: v1.8.7 (25c896a)" && \
    cd grpcurl && git log -1 --oneline && \
    echo "" && \
    echo "grpc-go: v1.56.2" && \
    cd /workspace/grpc-go && git log -1 --oneline && \
    echo "" && \
    echo "golang.org/x/net: v0.14.0 (VULNERABLE)" && \
    cd /workspace/net && git log -1 --oneline

WORKDIR /workspace
