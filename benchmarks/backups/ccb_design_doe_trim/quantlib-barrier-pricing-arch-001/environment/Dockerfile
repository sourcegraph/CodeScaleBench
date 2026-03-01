FROM gcc:14-bookworm

WORKDIR /workspace

# Install dependencies (libboost-dev = headers only; avoids MPI/gfortran conflicts on gcc:14)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    python3 \
    python3-pip \
    cmake \
    libboost-dev \
    && rm -rf /var/lib/apt/lists/*

# Clone QuantLib at pinned commit (v1.41)
RUN git clone --depth 1 https://github.com/sg-evals/QuantLib--dbdcc14e.git . && \
    git config user.email "agent@example.com" && \
    git config user.name "Agent"
