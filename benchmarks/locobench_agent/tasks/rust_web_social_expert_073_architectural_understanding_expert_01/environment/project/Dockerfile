# syntax=docker/dockerfile:1

################################################################################
# EduPulse Live – Event-Driven Social Learning Hub (web_social) – Dockerfile
#
# This multi-stage Dockerfile builds a lean, production-ready container image
# for the Rust backend API (`web_social`).  The image is <20 MB when compressed
# and contains only the compiled binary and its dynamic runtime libraries.
#
# Stages
#   1. Builder  – compiles dependencies & application with incremental caching
#   2. Runtime  – copies the resulting artefact into a minimal base image
#
# The resulting image can be used in Kubernetes, Nomad, docker-compose, etc.
# The binary exposes:
#   • :8080 – HTTP  (behind ingress TLS termination)
#   • :8443 – HTTPS (self-terminated TLS if enabled in config.toml)
################################################################################

# ------------------------------------------------------------------------------
# 1. Builder Stage
# ------------------------------------------------------------------------------
FROM rust:1.77-bookworm AS builder
LABEL org.opencontainers.image.source="https://github.com/edupulse/live" \
      org.opencontainers.image.title="EduPulse Live – Builder" \
      org.opencontainers.image.description="Build stage for web_social service"

# Speed-up subsequent builds by caching the cargo registry and git index layers
ENV CARGO_HOME=/cargo \
    RUST_BACKTRACE=1 \
    RUSTFLAGS="-C target-cpu=native"

# System libraries required during compilation
RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        pkg-config libssl-dev openssl musl-tools clang lld protobuf-compiler; \
    rm -rf /var/lib/apt/lists/*

# Create an unprivileged user to compile the sources
RUN useradd --create-home --shell /usr/sbin/nologin app
WORKDIR /usr/src/web_social
USER app

# --- Dependency Caching Trick -------------------------------------------------
# Copy the manifest files separately so that Docker can cache dependency builds
COPY --chown=app:app Cargo.toml Cargo.lock ./
# Create a dummy main.rs to satisfy `cargo build` while caching dependencies
RUN mkdir -p src && echo "fn main(){}" > src/main.rs

# Build only the dependencies (this layer is reused if Cargo.toml didn't change)
RUN --mount=type=cache,target=/cargo/registry \
    --mount=type=cache,target=/cargo/git \
    cargo build --release

# --- Actual App Source --------------------------------------------------------
# Now copy the real source code and re-compile the application
COPY --chown=app:app . .

RUN --mount=type=cache,target=/cargo/registry \
    --mount=type=cache,target=/cargo/git \
    cargo build --release

# ------------------------------------------------------------------------------
# 2. Runtime Stage
# ------------------------------------------------------------------------------
FROM debian:bookworm-slim AS runtime
LABEL org.opencontainers.image.source="https://github.com/edupulse/live" \
      org.opencontainers.image.title="EduPulse Live – web_social service" \
      org.opencontainers.image.description="Event-driven learning hub backend" \
      org.opencontainers.image.licenses="Apache-2.0"

ARG APP_USER=app
ENV APP_HOME=/opt/web_social \
    RUST_LOG=info \
    # OpenSSL can locate its certificates through this environment variable
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

# Install only the libraries required by the dynamically linked binary
RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates libssl3 tzdata; \
    rm -rf /var/lib/apt/lists/*

# Create a non-root user for security
RUN useradd --create-home --shell /usr/sbin/nologin "${APP_USER}"
WORKDIR ${APP_HOME}

# Copy the binary from the builder stage
COPY --from=builder --chown=${APP_USER}:${APP_USER} \
      /usr/src/web_social/target/release/web_social ./web_social

# Copy the sample production configuration shipped with the repository
# (The file can be overridden by mounting /opt/web_social/config.toml)
COPY --chown=${APP_USER}:${APP_USER} config/docker.toml ./config.toml

# Tighten permissions
RUN chmod 500 ./web_social && \
    chmod 400 ./config.toml

USER ${APP_USER}

# Ports:
#   8080 – HTTP traffic (can sit behind a reverse proxy / TLS terminator)
#   8443 – Optional self-terminated TLS endpoint
EXPOSE 8080 8443

# Basic liveness probe – hits the health endpoint every 30 s
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD wget -qO- http://localhost:8080/health || exit 1

ENTRYPOINT ["./web_social"]
CMD ["--config", "./config.toml"]