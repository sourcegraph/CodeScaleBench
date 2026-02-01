# ------------------------------------------------------------------------------
# VisuTility Orchestrator ‒ Container Recipe
#
# This multi-stage Dockerfile builds a fully-static, production-grade container
#   for the Rust-based computer-vision platform.  The first stage compiles the
#   code with incremental caching and optional sccache, while the final stage
#   ships only the resulting binary and *minimal* runtime shared libraries
#   required for OpenCV / FFmpeg acceleration.
#
#   Build   : docker buildx build -t visutility/orchestrator:latest .
#   Run     : docker run -p 8080:8080 visutility/orchestrator:latest
#   Inspect : docker exec -it <cid> sh
# ------------------------------------------------------------------------------

########################
# 1. Builder Stage
########################
FROM rust:1.73-slim-bullseye AS builder

# ----- Build-time arguments ----------------------------------------------------
ARG CARGO_PROFILE="release"
ARG SCCACHE_VERSION="v0.7.4"

# ----- Install system dependencies --------------------------------------------
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive \
    apt-get install -y --no-install-recommends \
      build-essential \
      pkg-config \
      cmake \
      clang \
      libssl-dev \
      libopencv-dev \
      ffmpeg \
      ca-certificates \
      curl && \
    rm -rf /var/lib/apt/lists/*

# ----- Optional: sccache for faster rebuilds ----------------------------------
RUN curl -sSL https://github.com/mozilla/sccache/releases/download/${SCCACHE_VERSION}/sccache-${SCCACHE_VERSION}-x86_64-unknown-linux-musl.tar.gz \
        | tar -xz && \
    mv sccache-*/sccache /usr/local/bin/ && \
    chmod +x /usr/local/bin/sccache

ENV RUSTC_WRAPPER="sccache"

# ----- Create non-root build user ---------------------------------------------
RUN useradd --create-home --shell /usr/sbin/nologin app
WORKDIR /home/app

# ----- Layered build cache: first copy manifests then sources -----------------
COPY ./Cargo.toml ./Cargo.lock ./
# Copy each crate manifest (improves caching for workspace changes)
RUN mkdir -p ./src && echo "fn main(){}" > ./src/main.rs

# Leverage BuildKit cache mounts
RUN --mount=type=cache,id=visutility-cargo-registry,target=/usr/local/cargo/registry \
    --mount=type=cache,id=visutility-cargo-git,target=/usr/local/cargo/git \
    cargo fetch --locked

# Now copy real sources
COPY ./ ./

# Build project
RUN --mount=type=cache,id=visutility-cargo-registry,target=/usr/local/cargo/registry \
    --mount=type=cache,id=visutility-cargo-git,target=/usr/local/cargo/git \
    --mount=type=cache,id=visutility-target,target=/home/app/target \
    cargo build --locked --${CARGO_PROFILE}

########################
# 2. Runtime Stage
########################
FROM debian:bookworm-slim AS runtime

LABEL org.opencontainers.image.title="VisuTility Orchestrator" \
      org.opencontainers.image.description="Production-grade Rust-based computer-vision platform." \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.licenses="Apache-2.0"

# Minimal system libs required by OpenCV + SSL
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive \
    apt-get install -y --no-install-recommends \
      libopencv-core408 \
      libopencv-imgcodecs408 \
      libopencv-imgproc408 \
      libopencv-videoio408 \
      libssl3 \
      ffmpeg \
      ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy dynamic libraries built in builder (if any static linking overrides)
COPY --from=builder /usr/lib/x86_64-linux-gnu/libopencv* /usr/lib/x86_64-linux-gnu/
COPY --from=builder /usr/local/lib/ /usr/local/lib/

# Create app user
ENV APP_USER=app
RUN useradd --create-home --shell /usr/sbin/nologin ${APP_USER}
WORKDIR /home/${APP_USER}

# Copy binary from builder
COPY --from=builder /home/app/target/release/visutility_orchestrator ./orchestrator

# Demote to non-root for security
USER ${APP_USER}

# Runtime configuration via env-vars
ENV RUST_BACKTRACE=1 \
    RUST_LOG=info,visutility_orchestrator=debug \
    MODEL_REGISTRY_URL="http://model-registry:8000" \
    METRICS_ENDPOINT="0.0.0.0:9090" \
    SERVER_PORT=8080

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD curl -fs http://localhost:${SERVER_PORT}/health || exit 1

# Default entrypoint
ENTRYPOINT ["./orchestrator"]
CMD ["--config", "/home/app/config/default.toml"]

# ------------------------------------------------------------------------------
# End of Dockerfile
# ------------------------------------------------------------------------------