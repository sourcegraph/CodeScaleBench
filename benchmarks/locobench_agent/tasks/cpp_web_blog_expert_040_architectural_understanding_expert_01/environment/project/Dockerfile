# ------------------------------------------------------------------
# IntraLedger BlogSuite – Production Dockerfile
#
# This Dockerfile produces a minimal, production-ready container
# image for BlogSuite using a multi-stage build:
#
#   1. builder  – full tool-chain to compile the C++ monolith
#   2. runtime  – stripped, non-root image with only runtime libs
#
# To build for multiple architectures (e.g. linux/amd64, linux/arm64):
#
#   docker buildx build --platform linux/amd64,linux/arm64 \
#       -t intraledger/blogsuite:latest --push .
# ------------------------------------------------------------------

############################
# 1. Builder Stage
############################
FROM ubuntu:22.04 AS builder

# Non-interactive frontend to avoid tzdata prompts, etc.
ARG DEBIAN_FRONTEND=noninteractive
ARG JOBS=4

# gcc-12 for improved C++20 support
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        gcc-12 g++-12 \
        cmake ninja-build ccache \
        git curl ca-certificates \
        libssl-dev \
        libpq-dev \
        libmariadb-dev-compat \
        libcurl4-openssl-dev \
        libboost-all-dev \
        libprotobuf-dev protobuf-compiler \
        zlib1g-dev \
        libicu-dev \
        libfmt-dev \
        && \
    update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-12 50 && \
    update-alternatives --install /usr/bin/g++ g++ /usr/bin/g++-12 50 && \
    rm -rf /var/lib/apt/lists/*

# Create working directory
WORKDIR /build

# Copy source code
# Use .dockerignore to keep context small (e.g., exclude build/, .git/, etc.)
COPY . /build

# Configure and build
RUN cmake -B build -G Ninja \
      -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_CXX_STANDARD=20 \
      -DCMAKE_C_COMPILER=gcc-12 \
      -DCMAKE_CXX_COMPILER=g++-12 \
      -DBLOGSUITE_ENABLE_TESTS=OFF \
      -DBLOGSUITE_ENABLE_LTO=ON && \
    cmake --build build -j ${JOBS} && \
    strip --strip-unneeded build/bin/blogsuite

############################
# 2. Runtime Stage
############################
FROM ubuntu:22.04 AS runtime

# Create non-root application user
RUN useradd --system --uid 10001 --create-home --shell /sbin/nologin blogsuite

# Install ONLY the libraries required at runtime
# (ldd /path/to/bin/blogsuite on builder to verify)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        libstdc++6 \
        libssl3 \
        libpq5 \
        libmariadb3 \
        libcurl4 \
        zlib1g \
        libicu70 \
        && \
    rm -rf /var/lib/apt/lists/*

# Set working directory and copy binary + assets
WORKDIR /opt/blogsuite
COPY --from=builder /build/build/bin/blogsuite .
COPY --from=builder /build/resources ./resources

# Create directory for configuration & uploaded files
RUN mkdir -p /etc/blogsuite /var/lib/blogsuite/uploads && \
    chown -R blogsuite:blogsuite /etc/blogsuite /var/lib/blogsuite /opt/blogsuite

# Switch to non-root user
USER blogsuite

# Expose default HTTP/HTTPS ports
EXPOSE 8080 8443

# Environment variables (override at run-time as needed)
ENV BLOGSUITE_ENV=production \
    BLOGSUITE_CONFIG=/etc/blogsuite/config.yaml \
    BLOGSUITE_DATA=/var/lib/blogsuite

# Healthcheck (simple TCP probe)
HEALTHCHECK --interval=30s --timeout=3s \
    CMD curl --fail http://localhost:8080/health || exit 1

# Start the application
ENTRYPOINT ["/opt/blogsuite/blogsuite"]
CMD ["--config", "/etc/blogsuite/config.yaml"]
