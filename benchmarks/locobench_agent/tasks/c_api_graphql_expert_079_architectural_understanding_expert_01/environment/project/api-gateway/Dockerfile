```dockerfile
#------------------------------------------------------------------------------
# SynestheticCanvas API-Gateway – Production Dockerfile
#
# This multi-stage Dockerfile compiles the high-performance C GraphQL/REST
# gateway and produces a minimal, security-hardened runtime image.
#
# The gateway is built with:
#   • CMake / Ninja                               – modern C build tooling
#   • libmicrohttpd, OpenSSL, zlib, nghttp2        – HTTP/2 + TLS transport
#   • graphqlparser, jansson                      – GraphQL + JSON support
#
# The resulting image is ~25 MB and runs as a non-root user.
#------------------------------------------------------------------------------

#############
#  BUILDER  #
#############
# syntax=docker/dockerfile:1.4
ARG BUILDPLATFORM
ARG TARGETPLATFORM
FROM --platform=$BUILDPLATFORM alpine:3.19 AS builder

LABEL stage="builder" \
      maintainer="engineering@synestheticcanvas.io"

# -----------------------------
# Install build dependencies
# -----------------------------
RUN apk add --no-cache --virtual .build-deps \
        build-base \
        cmake \
        ninja \
        git \
        openssl-dev \
        zlib-dev \
        libmicrohttpd-dev \
        nghttp2-dev \
        jansson-dev \
        graphqlparser-dev \
        linux-headers

# -----------------------------
# Copy source and build
# -----------------------------
WORKDIR /src

# Copy only build-relevant files first for better layer caching
COPY api-gateway/CMakeLists.txt               ./
COPY api-gateway/cmake/                       cmake/
# Then the rest of the source
COPY api-gateway/src/                         src/
COPY api-gateway/include/                     include/

# Build arguments propagated to CMake for reproducible builds
ARG GIT_SHA=unknown
ARG BUILD_TS=unknown

# Configure & compile
RUN cmake -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DSC_GIT_SHA=${GIT_SHA} \
        -DSC_BUILD_TS=${BUILD_TS} \
        -B build \
    && cmake --build build --parallel

#------------------------------
#   SECURITY: run unit tests
#------------------------------
RUN ctest --test-dir build --output-on-failure

################
#   RUNTIME    #
################
FROM alpine:3.19 AS runtime

LABEL org.opencontainers.image.title="SynestheticCanvas API Gateway" \
      org.opencontainers.image.description="Unified GraphQL/REST entrypoint for SynestheticCanvas microservices" \
      org.opencontainers.image.vendor="SynestheticCanvas" \
      org.opencontainers.image.authors="engineering@synestheticcanvas.io" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.revision="${GIT_SHA}"

# Non-root runtime user
RUN addgroup -S gateway && adduser -S gateway -G gateway

# Install only necessary runtime libs
RUN apk add --no-cache \
        libmicrohttpd \
        openssl \
        jansson \
        nghttp2 \
        zlib

WORKDIR /opt/synestheticcanvas

# Copy compiled binary and assets from builder
COPY --from=builder /src/build/synestheticcanvas-api-gateway ./gateway
COPY --from=builder /src/config ./config

# Grant execution rights
RUN chmod 0500 ./gateway

# Expose HTTP/1.1 + HTTP/2 secure port
EXPOSE 443/tcp

# Healthcheck: performs a lightweight ping on /healthz endpoint
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD \
    wget --no-check-certificate -q --https-only --spider https://localhost/healthz || exit 1

# Drop privileges permanently
USER gateway

# Default runtime arguments
ENV SC_ENV=production \
    SC_LOG_LEVEL=info \
    SC_CONFIG_FILE=/opt/synestheticcanvas/config/gateway.yaml

ENTRYPOINT ["./gateway"]
CMD ["--config", "${SC_CONFIG_FILE}"]
```