FROM gcc:14-bookworm

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    python3 \
    python3-pip \
    bison \
    flex \
    libreadline-dev \
    zlib1g-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN (adduser --disabled-password --gecos '' claude 2>/dev/null || true)

RUN mkdir -p /workspace && chown claude:claude /workspace

USER claude
WORKDIR /workspace
RUN git clone --depth 1 https://github.com/sg-evals/postgres--5a461dc4.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"
USER root

RUN mkdir -p /logs/agent /logs/verifier && \
    chown -R claude:claude /logs

ENTRYPOINT []
