FROM golang:1.19-bookworm

# Install tools needed for verification
RUN apt-get update && apt-get install -y \
    jq \
    bc \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Clone charmbracelet/wish at v0.5.0 (consuming project)
RUN git clone https://github.com/charmbracelet/wish.git && \
    cd wish && \
    git checkout v0.5.0 && \
    git log -1 --oneline | grep -E "^[a-f0-9]{7}" || echo "Pinned to tag v0.5.0"

# Clone gliderlabs/ssh at v0.3.4 (intermediate dependency)
RUN git clone https://github.com/gliderlabs/ssh.git && \
    cd ssh && \
    git checkout v0.3.4 && \
    git log -1 --oneline | grep -E "^[a-f0-9]{7}" || echo "Pinned to tag v0.3.4"

# Clone golang.org/x/crypto at vulnerable commit (June 2021)
# This is the version referenced by gliderlabs/ssh v0.3.4: v0.0.0-20210616213533-5ff15b29337e
RUN git clone https://go.googlesource.com/crypto && \
    cd crypto && \
    git checkout 5ff15b29337e && \
    git log -1 --oneline | grep -E "^5ff15b2" || echo "Failed to verify crypto commit"

# Verify the dependency chain in go.mod files
RUN echo "=== Verifying Dependency Chain ===" && \
    echo "wish v0.5.0 go.mod:" && \
    grep "gliderlabs/ssh" wish/go.mod && \
    echo "gliderlabs/ssh v0.3.4 go.mod:" && \
    grep "golang.org/x/crypto" ssh/go.mod && \
    echo "Dependency chain verified!"

# Create logs directory
RUN mkdir -p /logs/agent

WORKDIR /workspace
