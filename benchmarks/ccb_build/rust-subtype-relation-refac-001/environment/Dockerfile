FROM ghcr.io/sourcegraph/ccb-repo-rust-01f6ddf7 AS rust-src

FROM rust:1.82-bookworm

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY --from=rust-src /workspace /workspace

RUN git config user.email "agent@example.com" && \
    git config user.name "Agent"
