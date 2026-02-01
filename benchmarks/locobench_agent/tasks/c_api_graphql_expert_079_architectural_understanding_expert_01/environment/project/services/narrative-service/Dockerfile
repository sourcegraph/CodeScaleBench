# syntax=docker/dockerfile:1.4
#
# ──────────────────────────────────────────────────────────────────────────────
#  SynestheticCanvas Narrative-Service
#  Production-grade, multi-stage Dockerfile
# ──────────────────────────────────────────────────────────────────────────────
#
#  This image builds and ships the C-based “narrative-service” microservice.
#  The build is completely self-contained, reproducible, and produces a
#  minimal, non-root runtime image.  The resulting container is ready for
#  orchestration in Kubernetes, Nomad, Docker Swarm, or standalone use.
#
#  Targets
#  ───────
#    • builder   – Compiles and tests the binary
#    • runtime   – Ultra-slim image with the stripped binary
#
#  Usage
#  ─────
#    docker build \
#      --build-arg NARRATIVE_VERSION=$(git describe --tags --always) \
#      --build-arg VCS_REF=$(git rev-parse --short HEAD) \
#      --build-arg BUILD_DATE=$(date -u +'%Y-%m-%dT%H:%M:%SZ') \
#      -t ghcr.io/synestheticcanvas/narrative-service:latest .
#
# ──────────────────────────────────────────────────────────────────────────────

########################
# Stage 1 – Build
########################
FROM --platform=$BUILDPLATFORM alpine:3.19 AS builder

# Build-time metadata
ARG NARRATIVE_VERSION=dev
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown

LABEL org.opencontainers.image.source="https://github.com/SynestheticCanvas/api_graphql" \
      org.opencontainers.image.description="Narrative-Service build stage" \
      org.opencontainers.image.revision=$VCS_REF \
      org.opencontainers.image.created=$BUILD_DATE

# Install build toolchain & dependencies
RUN apk add --no-cache --virtual .build-deps \
        build-base \
        ninja \
        cmake \
        git \
        bash \
        pkgconfig \
        libevent-dev \
        libgraphqlparser-dev \
        openssl-dev \
        zlib-dev && \
    addgroup -S app && adduser -S -G app app

USER app
WORKDIR /home/app/src

# Copy project sources into the build context
COPY --chown=app:app . .

# Configure, compile, and run unit tests
RUN cmake -Bbuild -GNinja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=/home/app/dist \
        -DNARRATIVE_VERSION=$NARRATIVE_VERSION \
        -DGRAPHQLPARSER_BUILD_SHARED=OFF \
        -DCMAKE_EXE_LINKER_FLAGS="-static" && \
    cmake --build build --parallel $(nproc) && \
    ctest --test-dir build --output-on-failure && \
    cmake --install build && \
    strip /home/app/dist/bin/narrative-service

########################
# Stage 2 – Runtime
########################
FROM alpine:3.19 AS runtime

ARG NARRATIVE_VERSION=dev
ARG VCS_REF=unknown
ARG BUILD_DATE=unknown

# OCI-compliant image metadata
LABEL org.opencontainers.image.title="SynestheticCanvas Narrative Service" \
      org.opencontainers.image.description="Branching-narrative microservice powering SynestheticCanvas." \
      org.opencontainers.image.version=$NARRATIVE_VERSION \
      org.opencontainers.image.revision=$VCS_REF \
      org.opencontainers.image.created=$BUILD_DATE \
      org.opencontainers.image.licenses="MIT"

# Runtime dependencies (keep minimal)
RUN apk add --no-cache libevent libgraphqlparser openssl zlib && \
    addgroup -S app && adduser -S -G app app

USER app
WORKDIR /home/app

# Copy the statically linked artifact from the builder stage
COPY --from=builder /home/app/dist /home/app

# Service port
ENV NARRATIVE_SERVICE_PORT=7070
EXPOSE ${NARRATIVE_SERVICE_PORT}/tcp

# Health check – verify TCP connectivity
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD \
  nc -z 127.0.0.1 ${NARRATIVE_SERVICE_PORT} || exit 1

# Default command / entrypoint
ENTRYPOINT ["./bin/narrative-service"]
CMD ["--config", "/etc/synesthetic/narrative.yml"]
