# syntax=docker/dockerfile:1.4

###############################################################################
# Build stage
###############################################################################
FROM --platform=$BUILDPLATFORM debian:bookworm-slim AS builder

ARG TARGETPLATFORM
ARG BUILDPLATFORM
ARG GIT_SHA=unknown
ARG BUILD_DATE=unknown

LABEL org.opencontainers.image.title="SynestheticCanvas Palette Service" \
      org.opencontainers.image.description="Color palette management micro-service written in C" \
      org.opencontainers.image.source="https://github.com/SynestheticCanvas/palette-service" \
      org.opencontainers.image.revision=$GIT_SHA \
      org.opencontainers.image.created=$BUILD_DATE \
      maintainer="SynestheticCanvas Engineering <engineering@synestheticcanvas.io>"

# ---------------------------------------------------------------------------
# Install build toolchain and development libraries
# ---------------------------------------------------------------------------
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        pkg-config \
        git \
        curl \
        libssl-dev \
        libpq-dev \
        libcjson-dev \
        && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Prepare build workspace
# ---------------------------------------------------------------------------
WORKDIR /usr/src/palette-service

# Copy manifests first to leverage Docker layer caching
COPY CMakeLists.txt .
COPY cmake/          ./cmake/
COPY third_party/    ./third_party/

# Pre-build third-party static libs and cache them
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DSC_BUILD_TESTS=OFF \
    && cmake --build build --target deps -j$(nproc)

# Copy the remaining source code
COPY include/ ./include/
COPY src/     ./src/

# Build the service binary
RUN cmake --build build --target sc-palette-service -j$(nproc) && \
    strip build/bin/sc-palette-service

###############################################################################
# Runtime stage
###############################################################################
FROM debian:bookworm-slim AS runtime

# ---------------------------------------------------------------------------
# Install only the runtime libraries required by the palette service
# ---------------------------------------------------------------------------
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        libssl3 \
        libpq5 \
        ca-certificates \
        wget \
        && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
# Create non-root user
# ---------------------------------------------------------------------------
RUN useradd -r -u 10001 -g nogroup palette

# ---------------------------------------------------------------------------
# Copy the built artifact
# ---------------------------------------------------------------------------
COPY --from=builder /usr/src/palette-service/build/bin/sc-palette-service /usr/local/bin/palette-service

# Runtime directories & permissions
RUN mkdir -p /var/lib/sc /etc/sc && chown -R palette:nogroup /var/lib/sc /etc/sc

USER palette
WORKDIR /var/lib/sc

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------
ENV PALETTE_SERVICE_PORT=8082 \
    SC_LOG_LEVEL=INFO \
    SC_MAX_CONNECTIONS=128 \
    SC_DATABASE_URL="postgresql://sc_palette:secret@db:5432/sc_palette" \
    SC_GRAPHQL_SCHEMA=/etc/sc/schema/palette.graphql

EXPOSE 8082

# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s CMD \
  wget -qO- http://127.0.0.1:${PALETTE_SERVICE_PORT}/healthz | grep -q "ok" || exit 1

# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
ENTRYPOINT ["/usr/local/bin/palette-service"]
CMD ["--config", "/etc/sc/palette-service.toml"]