FROM python:3.12-bookworm

# Install system dependencies (including build tools for Cython extensions)
RUN apt-get update && apt-get install -y --no-install-recommends \
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
    cython \
    numpy \
    scipy \
    joblib \
    threadpoolctl

# Clone scikit-learn at pinned commit directly into workspace
RUN git clone --depth 1 https://github.com/sg-evals/scikit-learn--cb7e82dd.git /workspace/original && \
    cd /workspace/original && \
    git submodule update --init --recursive

# Create optimized copy (agent works here)
RUN cp -a /workspace/original/. /workspace/optimized/

# Install scikit-learn from source
RUN cd /workspace/optimized && \
    pip install --no-cache-dir . 2>&1 | tail -10

# Copy relevant test suite
RUN cp -r /workspace/original/sklearn/cluster/tests /workspace/tests/cluster_tests 2>/dev/null || true

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
