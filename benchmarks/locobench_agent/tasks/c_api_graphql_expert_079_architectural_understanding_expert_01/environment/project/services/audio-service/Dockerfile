# syntax=docker/dockerfile:1.4
###############################################################################
# SynestheticCanvas – Audio-Service Dockerfile
#
# This image is responsible for compiling and running the audio-reactive
# micro-service written in C.  It follows a multi-stage strategy in order to
# ship a minimal, non-root, production-ready container that includes
# only the runtime artifacts required to serve traffic.
#
# ┌──────────────────────────────┐
# │          Build Stage         │  ──► Compiles the source code and runs
# └──────────────────────────────┘      unit tests inside an Alpine builder.
#                  │
#                  ▼
# ┌──────────────────────────────┐
# │         Runtime Stage        │  ──► Copies the binaries into a distroless
# └──────────────────────────────┘      image for optimal security & size.
#
###############################################################################

##########################
# 1. Build Stage
##########################
FROM --platform=$BUILDPLATFORM alpine:3.19 AS builder

# Build arguments allow the CI to pin revisions without editing the Dockerfile.
ARG AUDIO_SERVICE_VERSION=main
ARG AUDIO_SERVICE_COMMIT=unknown

LABEL org.opencontainers.image.source="https://github.com/SynestheticCanvas/audio-service" \
      org.opencontainers.image.description="SynestheticCanvas – Audio-Reactive Microservice" \
      org.opencontainers.image.version="${AUDIO_SERVICE_VERSION}" \
      org.opencontainers.image.revision="${AUDIO_SERVICE_COMMIT}"

# Required packages: MUSL toolchain, clang/llvm, cmake + ninja, dev libraries.
RUN --mount=type=cache,target=/var/cache/apk \
    apk add --no-cache \
        build-base \
        clang \
        llvm \
        cmake \
        ninja \
        git \
        libsndfile-dev \
        libsamplerate-dev \
        ffmpeg-libs-dev

WORKDIR /workspace

# Copy source tree last to maximize caching of layer installs.
COPY . .

# Build with CMake + Ninja
RUN cmake -B build -S . \
      -G Ninja \
      -DCMAKE_BUILD_TYPE=Release \
      -DAUDIO_SERVICE_VERSION=${AUDIO_SERVICE_VERSION} \
      -DWERROR=ON \
 && cmake --build build --parallel $(nproc)

# Optional: run unit tests (will fail build on error).
RUN ctest --test-dir build --output-on-failure

##########################
# 2. Runtime Stage
##########################
# Utilize a distroless image for minimal attack-surface; gcompat provides
# basic glibc shims for MUSL-linked binaries when necessary.
FROM gcr.io/distroless/cc-debian12@sha256:225c957dcf9863c7d8a8b6ed01894dc4515575e0f8d11e7817074e99ad84653f AS runtime

# Non-root user for security-first deployments.
ENV RUN_USER=scsvc
ENV RUN_UID=10001
RUN useradd --uid ${RUN_UID} --system --home /app --shell /sbin/nologin ${RUN_USER}

WORKDIR /app

# Copy compiled artifacts from the builder stage.
COPY --from=builder /workspace/build/audio-service /app/audio-service
COPY --from=builder /workspace/config ./config

# Application port (documentational—distroless ignores EXPOSE'd ports).
EXPOSE 8080/tcp

# Health-check probes for orchestrators (Docker, Kubernetes, etc.).
# The audio-service responds to GET /healthz with 200 OK.
HEALTHCHECK --interval=30s --timeout=2s --start-period=10s --retries=3 \
  CMD wget --spider --quiet http://127.0.0.1:8080/healthz || exit 1

# Drop privileges and start the service.
USER ${RUN_USER}:${RUN_USER}
ENTRYPOINT ["/app/audio-service"]

###############################################################################
# End of Dockerfile
###############################################################################