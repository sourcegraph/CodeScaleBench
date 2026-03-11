FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    python3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Clone repo at pinned version
RUN git clone --depth 1 https://github.com/sg-evals/godot--4.3-stable.git . && \
    git config user.email "agent@benchmark.local" && \
    git config user.name "Agent"

# Create logs directory for agent output
RUN mkdir -p /logs/agent /logs/verifier
RUN chown -R claude:claude /logs

# Pre-create claude user and set ownership at build time
RUN (adduser --disabled-password --gecos '' claude 2>/dev/null || true) && \
    for d in /workspace /logs; do [ -d "$d" ] && chown -R claude:claude "$d"; done || true

ENTRYPOINT []
