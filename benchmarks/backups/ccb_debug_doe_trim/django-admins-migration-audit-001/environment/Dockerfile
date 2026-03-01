FROM python:3.12-bookworm

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Clone Django at the commit just before the ADMINS/MANAGERS migration
# Commit e295033 is the migration commit; this mirror is pinned to its parent (aed303af)
RUN git clone --depth 1 https://github.com/sg-evals/django--aed303af.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Create output directories
RUN mkdir -p /logs/agent /logs/verifier
