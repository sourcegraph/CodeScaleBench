# cb-multi-swe-bench__go__maintenance__bugfix__3d85271b — baseline (full local source)
FROM golang:1.23-bookworm

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates python3 curl \
    && rm -rf /var/lib/apt/lists/*

RUN if ! command -v node > /dev/null 2>&1; then \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs; \
    fi

RUN (adduser --disabled-password --gecos '' claude 2>/dev/null || true) && \
    mkdir -p /workspace && chown claude:claude /workspace

USER claude
RUN git clone --depth 1 https://github.com/sg-evals/cli--c6a693c4.git /workspace
USER root

RUN mkdir -p /logs/agent /logs/verifier
RUN chown -R claude:claude /workspace /logs

WORKDIR /workspace
ENTRYPOINT []
