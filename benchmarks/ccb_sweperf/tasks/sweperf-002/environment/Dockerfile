FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    time \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager for fast installs
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Create working directories
RUN mkdir -p /workspace /logs /benchmark

# Install benchmarking and profiling tools
RUN pip install --no-cache-dir \
    pytest \
    pytest-benchmark \
    pyperf \
    memory_profiler \
    line_profiler \
    numpy

# Copy repository/project files
# SWE-Perf tasks operate on specific repos
WORKDIR /workspace

# Set up benchmark environment
ENV BENCHMARK_ITERATIONS=10
ENV BENCHMARK_WARMUP=3

# Task-specific metadata
ENV TASK_ID="sweperf-002"
ENV REPO_NAME="scikit-learn"
ENV TARGET_FUNCTION="sklearn.cluster._k_means._kmeans_single_elkan"
ENV BASELINE_RUNTIME="0.182"

CMD ["/bin/bash"]
