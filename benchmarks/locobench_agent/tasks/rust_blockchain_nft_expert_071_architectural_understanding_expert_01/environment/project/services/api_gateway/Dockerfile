# ------------------------------------------------------------------------------
# Dockerfile for CanvasChain Symphony – API Gateway Micro-service
#
# This image performs a multi-stage build:
#   1. Compile the Rust project in a clean, reproducible environment
#   2. Copy the stripped release binary into a minimal, non-root runtime image
#
# The result is a small, secure container that can run anywhere.
# ------------------------------------------------------------------------------

########################
# 1. Builder Stage 🛠️  #
########################
FROM rust:1.72-bullseye AS builder

# ------------------------------------------------------------------
# ARGs allow callers to customise the build without editing Dockerfile
# ------------------------------------------------------------------
ARG SERVICE_NAME=api_gateway
ARG APP_USER=canvas
ARG APP_USER_UID=10001

# Install system dependencies required for building Rust services that use:
#   * tonic / prost (gRPC)              – needs `protoc`
#   * openssl (TLS)                     – needs headers
#   * various crates that shell out to  – needs build tools
# ------------------------------------------------------------------
RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        clang \
        cmake \
        pkg-config \
        libssl-dev \
        protobuf-compiler; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/*

# Create an unprivileged user for running the final image
RUN useradd --create-home \
            --shell /usr/sbin/nologin \
            --uid "${APP_USER_UID}" \
            "${APP_USER}"

WORKDIR /usr/src/${SERVICE_NAME}

# ------------------------------------------------------------------
# Caching dependencies:
#   Copy only the manifests first so Docker can re-use build layers
# ------------------------------------------------------------------
COPY Cargo.toml Cargo.lock ./
# If using a workspace, bring top-level manifest as well
# COPY ../../Cargo.toml ../../

# Minimal source stub to satisfy `cargo build` dependency resolution
RUN mkdir -p src && \
    echo 'fn main() { /* dummy build stub */ }' > src/main.rs

# Compile dependencies (will be cached unless manifests change)
RUN cargo build --release && rm -rf src

# ------------------------------------------------------------------
# Copy the actual source code and compile the real binary
# ------------------------------------------------------------------
COPY . .

# Compile using musl for static linking if desired:
#   RUN rustup target add x86_64-unknown-linux-musl && \
#       cargo build --release --target x86_64-unknown-linux-musl
#
# For most cases glibc is fine and yields smaller images when stripped
RUN set -eux; \
    cargo build --release --locked; \
    strip target/release/${SERVICE_NAME}

##############################
# 2. Runtime Stage 🚀        #
##############################
FROM gcr.io/distroless/cc-debian11 AS runtime

ARG APP_USER=canvas
ARG APP_USER_UID=10001
ARG SERVICE_NAME=api_gateway

# Copy the release binary from the builder
COPY --from=builder /usr/src/${SERVICE_NAME}/target/release/${SERVICE_NAME} /usr/local/bin/${SERVICE_NAME}

# (Optional) Copy static assets such as OpenAPI spec or templates
# COPY --from=builder /usr/src/${SERVICE_NAME}/assets /srv/${SERVICE_NAME}/assets

# Expose service ports
#   8080 – REST / HTTP
#   9090 – gRPC
# ------------------------------------------------------------------
EXPOSE 8080/tcp
EXPOSE 9090/tcp

# Switch to non-root user for security
USER ${APP_USER_UID}

# Environment defaults (can be overridden at run-time via `docker run -e`)
ENV RUST_LOG=info \
    CANVAS_ENV=production \
    OTEL_SERVICE_NAME=${SERVICE_NAME}

# Health-check pings the built-in endpoint `--healthcheck` (fast, no TLS)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD ["/usr/local/bin/api_gateway", "--healthcheck"]

# Launch 🚀
ENTRYPOINT ["/usr/local/bin/api_gateway"]