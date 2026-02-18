FROM python:3.12-bookworm

# Install system dependencies (including build tools for numpy C extensions)
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    curl \
    gfortran \
    git \
    jq \
    libopenblas-dev \
    liblapack-dev \
    pkg-config \
    time \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager for fast installs
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Create working directories
RUN mkdir -p /workspace/original /workspace/optimized /workspace/tests /logs /benchmark

# Install benchmarking and profiling tools
RUN pip install --no-cache-dir \
    pytest \
    pytest-benchmark \
    pyperf \
    memory_profiler \
    line_profiler \
    cython

# Clone numpy at pinned commit directly into workspace
RUN git clone https://github.com/numpy/numpy.git /workspace/original && \
    cd /workspace/original && \
    git fetch origin a639fbf5d2a4fb789967124d16f503f57bd5958b && \
    git checkout a639fbf5d2a4fb789967124d16f503f57bd5958b && \
    git submodule update --init --recursive

# Create optimized copy (agent works here)
RUN cp -a /workspace/original/. /workspace/optimized/

# Install numpy from source
RUN cd /workspace/optimized && \
    pip install --no-cache-dir . 2>&1 | tail -10

# Copy test suite for convenience
RUN cp -r /workspace/original/numpy/_core/tests /workspace/tests/core_tests 2>/dev/null || true

WORKDIR /workspace

# Set up benchmark environment
ENV BENCHMARK_ITERATIONS=10
ENV BENCHMARK_WARMUP=3

# Task-specific metadata
ENV TASK_ID="sweperf-001"
ENV REPO_NAME="numpy"
ENV TARGET_FUNCTION="numpy.core.multiarray.array_sum"
ENV BASELINE_RUNTIME="0.045"

CMD ["/bin/bash"]
