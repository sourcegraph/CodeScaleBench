FROM python:3.11-slim

WORKDIR /workspace

# Install basic utilities
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Set up workspace
RUN chmod 777 /workspace
