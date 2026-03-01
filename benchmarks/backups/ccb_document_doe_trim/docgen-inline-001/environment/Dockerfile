FROM python:3.12-bookworm

WORKDIR /workspace

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ripgrep \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/sg-evals/django--674eda1c.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

RUN mkdir -p /app
