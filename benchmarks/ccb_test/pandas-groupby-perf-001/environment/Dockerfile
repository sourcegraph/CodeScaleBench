FROM python:3.12-bookworm

# Install system dependencies (including build tools for Cython extensions)
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    curl \
    git \
    jq \
    pkg-config \
    time \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager for fast installs
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Create working directories
RUN mkdir -p /workspace/original /workspace/optimized /workspace/tests /logs /benchmark

# Install benchmarking and profiling tools + pandas build dependencies
RUN pip install --no-cache-dir \
    pytest \
    pytest-benchmark \
    pyperf \
    memory_profiler \
    line_profiler \
    cython \
    numpy \
    meson-python \
    meson \
    versioneer

# Clone pandas at pinned commit directly into workspace
RUN git clone https://github.com/pandas-dev/pandas.git /workspace/original && \
    cd /workspace/original && \
    git fetch origin 41968da5f87873dd49b2cff1da853c90181f7f89 && \
    git checkout 41968da5f87873dd49b2cff1da853c90181f7f89 && \
    git submodule update --init --recursive

# Create optimized copy (agent works here)
RUN cp -a /workspace/original/. /workspace/optimized/

# Install pandas from source
RUN cd /workspace/optimized && \
    pip install --no-cache-dir . 2>&1 | tail -10

# Copy relevant test suite
RUN cp -r /workspace/original/pandas/tests/groupby /workspace/tests/groupby_tests 2>/dev/null || true

WORKDIR /workspace

# Set up benchmark environment
ENV BENCHMARK_ITERATIONS=10
ENV BENCHMARK_WARMUP=3

# Task-specific metadata
ENV TASK_ID="sweperf-003"
ENV REPO_NAME="pandas"
ENV TARGET_FUNCTION="pandas.core.groupby.ops.GroupBy._aggregate_series_fast"
ENV BASELINE_RUNTIME="0.095"

CMD ["/bin/bash"]
