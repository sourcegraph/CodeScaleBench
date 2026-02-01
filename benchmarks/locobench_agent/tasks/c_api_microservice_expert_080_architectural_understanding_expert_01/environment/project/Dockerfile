# syntax=docker/dockerfile:1
#
# MercuryMonolith Commerce Hub – Dockerfile
# -----------------------------------------
# Multi-stage build that compiles the statically-linked Mercury binary and
# ships it in a minimal, non-root runtime image.  Designed for predictable
# latency, small footprint, and straightforward on-prem deployments.
#
#   Runtime ports
#     8080  – HTTP / REST & GraphQL traffic
#     9180  – Prometheus metrics endpoint
#
#   Health-check
#     Invokes the built-in “--healthcheck” command which returns 0 on success.
#
#   Environment variables
#     MERCURY_ENV           – one of: development | staging | production
#     MERCURY_HTTP_PORT     – listening port (default: 8080)
#     MERCURY_LOG_LEVEL     – trace | debug | info | warn | error (default: info)
#     MERCURY_DB_URL        – PostgreSQL or SQLite connection string
#
# Build arguments
#     MERCURY_GIT_SHA       – injected by CI for traceability
#     MERCURY_BUILD_DATE    –            ″
# -----------------------------------------------------------------------------

#############################
# 1. Build stage – toolchain #
#############################
FROM debian:stable-slim AS builder

# Install build toolchain and required dev libraries
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
        build-essential  \
        cmake            \
        git              \
        ca-certificates  \
        libpq-dev        \
        libsqlite3-dev   \
        libssl-dev       \
        zlib1g-dev       && \
    rm -rf /var/lib/apt/lists/*

# Directory layout inside the container
ENV APP_HOME=/opt/mercury
WORKDIR ${APP_HOME}

# Optional metadata for “--version” output
ARG MERCURY_GIT_SHA=unknown
ARG MERCURY_BUILD_DATE=unknown
ENV MERCURY_GIT_SHA=${MERCURY_GIT_SHA}
ENV MERCURY_BUILD_DATE=${MERCURY_BUILD_DATE}

# Copy the entire repository (assumes Docker build context = repo root)
COPY . .

# -----------------------------------------------------------------------------
# CMake build
#   -DENABLE_STATIC=ON attempts full static link to allow a distroless runtime
#   --target mercury_hub expects a top-level CMake target producing the binary
# -----------------------------------------------------------------------------
RUN cmake -B build -S . -DCMAKE_BUILD_TYPE=Release -DENABLE_STATIC=ON \
    && cmake --build build --target mercury_hub -- -j$(nproc)

###################################
# 2. Runtime stage – distroless cc #
###################################
FROM gcr.io/distroless/cc-debian11@sha256:6f7e4c1e1af7288ab3b25e838304479b5d8fc0c9e22d0edb1542ee4789c8a3db AS runtime

# Copy the statically-linked binary and the root CA bundle
COPY --from=builder /opt/mercury/build/mercury_hub       /usr/local/bin/mercury_hub
COPY --from=builder /etc/ssl/certs/ca-certificates.crt   /etc/ssl/certs/

# Runtime user – non-root for better security (UID 10001 chosen arbitrarily)
USER 10001:0

# Application defaults (can be overridden at “docker run” time)
ENV MERCURY_ENV=production \
    MERCURY_HTTP_PORT=8080 \
    MERCURY_LOG_LEVEL=info \
    MERCURY_DB_URL=postgres://merc_user:changeit@db/mercury \
    TZ=UTC

WORKDIR /data
EXPOSE 8080 9180

# Lightweight health-check leveraging the binary itself
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD ["/usr/local/bin/mercury_hub", "--healthcheck"]

# Launch the monolith
ENTRYPOINT ["/usr/local/bin/mercury_hub"]