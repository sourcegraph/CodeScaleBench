FROM python:3.11-bookworm

WORKDIR /workspace

# Install dependencies
RUN apt-get update && apt-get install -y \
    git \
    curl \
    npm \
    build-essential \
    cmake \
    ninja-build

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Clone the actual TensorRT-LLM repository
# This ensures BOTH baseline and MCP agents have identical file access
RUN git clone --depth 1 https://github.com/NVIDIA/TensorRT-LLM.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"

# Install Python dependencies (basic setup only)
# Full build may require CUDA and other deps, but we need the source files
RUN pip install --upgrade pip && \
    pip install pybind11 2>&1 || true

# Task setup complete
# Note: Both baseline and MCP agents now have access to the real TensorRT-LLM source.
# Baseline will use local grep/find/rg. MCP will use Sourcegraph semantic search.
