FROM debian:bookworm-slim

# Install git, jq, bc for verifier
RUN apt-get update && apt-get install -y git jq bc && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Clone curl at pre-fix commit (vulnerable version)
# CVE-2023-38545 SOCKS5 heap buffer overflow
# Pre-fix commit: 09e25b9d94f4106eac8ca3a43b221bdc66f405e4 (parent of fix fb4415d8)
RUN git clone --filter=blob:none --no-checkout https://github.com/curl/curl.git && \
    cd curl && \
    git checkout 09e25b9d94f4106eac8ca3a43b221bdc66f405e4 && \
    git log -1 --oneline | grep "09e25b9" || (echo "ERROR: Wrong commit checked out" && exit 1)

# Set git config for potential agent commits (though task is analysis-only)
RUN cd curl && git config user.email "agent@benchmark.local" && git config user.name "Agent"
