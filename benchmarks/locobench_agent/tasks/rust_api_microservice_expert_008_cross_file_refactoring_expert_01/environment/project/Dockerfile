# -----------------------------------------------------------------------------
# LedgerLink Nexus | Production Dockerfile
# -----------------------------------------------------------------------------
# Multi-stage build leveraging BuildKit for optimal caching and
# minimal runtime image size.  The final image is a non-root,
# distroless container containing only the compiled binary,
# dynamic OpenSSL libs, tzdata and minimal CA certificates.
# -----------------------------------------------------------------------------

#########################   Builder   #########################################

# 1. Build dependencies + toolchain (isolated)
FROM rust:1.74-slim AS chef
LABEL stage=chef

# Install build utilities & system dependencies required by crates
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive \
    apt-get install -y --no-install-recommends \
        pkg-config \
        libssl-dev \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Leverage cargo-chef for reproducible, cache-friendly builds
RUN cargo install cargo-chef --locked

WORKDIR /usr/src/ledgerlink

# 2. Prime the cargo dependency graph layer
FROM chef AS planner
COPY Cargo.toml Cargo.lock ./
# Copy workspace manifests if monorepo
COPY crates ./crates
RUN cargo chef prepare --recipe-path recipe.json

# 3. Build dependencies
FROM chef AS cacher
COPY --from=planner /usr/src/ledgerlink/recipe.json recipe.json
RUN cargo chef cook --release --recipe-path recipe.json

# 4. Compile application
FROM chef AS builder
# Copy compiled dependencies from cache layer
COPY --from=cacher /usr/src/ledgerlink/target /usr/src/ledgerlink/target
COPY --from=cacher /usr/local/cargo /usr/local/cargo
# Copy source code last to maximize cache hits
COPY . .

# Build with all production-only features enabled, stripping debug symbols
ARG GIT_SHA=unknown
ENV RUSTFLAGS="-C target-cpu=native"
RUN cargo build --release --bin ledgerlink-nexus \
    --features "server,graphql,production" && \
    # Embed git commit for traceability
    printf "cargo:rustc-env=GIT_SHA=%s\n" "$GIT_SHA" >> .cargo/config

#########################   Runtime   #########################################

FROM gcr.io/distroless/cc-debian12 AS runtime
LABEL org.opencontainers.image.title="LedgerLink Nexus" \
      org.opencontainers.image.description="Ultra-reliable, versioned API microservice for B2B financial reconciliation." \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/ledgerlink/nexus" \
      org.opencontainers.image.revision=$GIT_SHA

# Install runtime libs (OpenSSL, tzdata)
COPY --from=builder /usr/lib/x86_64-linux-gnu/libssl.so.* /usr/lib/x86_64-linux-gnu/
COPY --from=builder /usr/lib/x86_64-linux-gnu/libcrypto.so.* /usr/lib/x86_64-linux-gnu/
COPY --from=builder /usr/share/zoneinfo /usr/share/zoneinfo
COPY --from=builder /etc/ssl/certs /etc/ssl/certs

# Copy the release binary
COPY --from=builder /usr/src/ledgerlink/target/release/ledgerlink-nexus /usr/local/bin/ledgerlink-nexus

# Security: create non-root user with minimal permissions
USER 1001:0

# Application runtime configuration
ENV RUST_LOG="ledgerlink=info,actix_web=info" \
    ROCKET_ENV=production \
    TZ=UTC \
    APP_ENV=prod

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s CMD ["/usr/local/bin/ledgerlink-nexus", "--healthcheck"]

ENTRYPOINT ["/usr/local/bin/ledgerlink-nexus"]