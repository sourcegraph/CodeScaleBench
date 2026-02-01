# syntax=docker/dockerfile:1.4

################################################################################
#                           CHIRPPULSE ― BUILDER STAGE                         #
################################################################################
ARG RUST_VERSION=1.72.1
FROM rust:${RUST_VERSION}-slim-buster AS builder

LABEL org.opencontainers.image.source="https://github.com/chirppulse/chirppulse" \
      org.opencontainers.image.description="ChirpPulse ‒ Real-Time Social Sentiment Lake" \
      maintainer="infra@chirppulse.io"

# Install system-level dependencies required for compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
        pkg-config \
        libssl-dev \
        librdkafka-dev \
        protobuf-compiler \
        build-essential \
        ca-certificates \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user that will own the running process in the final image
ARG USER=chirppulse
ARG UID=10001
RUN useradd --create-home --uid ${UID} --shell /usr/sbin/nologin ${USER}

WORKDIR /opt/chirppulse

# 1. Pre-copy only the manifest files so that Docker layer caching works
COPY Cargo.toml Cargo.lock ./

# 2. Gather dependency tree and build it (dummy) to cache expensive compilation
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/opt/chirppulse/target \
    cargo fetch

# 3. Copy the full source tree & build the application
COPY . .

# Build in release mode for a small, optimized binary
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/opt/chirppulse/target \
    RUSTFLAGS="-C target-cpu=native" \
    cargo build --release --features "rdkafka,metrics,rocksdb"

################################################################################
#                           CHIRPPULSE ― RUNTIME STAGE                         #
################################################################################
FROM debian:buster-slim AS runtime

ENV APP_HOME=/opt/chirppulse \
    RUST_LOG=info \
    KAFKA_BROKERS=localhost:9092 \
    SERVICE_PORT=8080

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        librdkafka1 \
        libssl1.1 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy the non-root user definition from the builder
ARG USER=chirppulse
ARG UID=10001
RUN useradd --create-home --uid ${UID} --shell /usr/sbin/nologin ${USER}

WORKDIR ${APP_HOME}

# Copy the statically linked binary from the builder stage
COPY --from=builder /opt/chirppulse/target/release/chirppulse ./chirppulse

# Ensure appropriate file permissions
RUN chown -R ${USER}:${USER} ${APP_HOME}

USER ${USER}

EXPOSE ${SERVICE_PORT}

# Basic healthcheck hitting the built-in /health endpoint (if available)
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD curl --fail http://127.0.0.1:${SERVICE_PORT}/health || exit 1

# Default command
ENTRYPOINT ["./chirppulse"]