#------------------------------------------------------------------------------
# SynestheticCanvas Texture Service – Production Dockerfile
#
# This Dockerfile produces a small, security-hardened container image that
# hosts the Texture micro-service.  The service is written in C and uses
# CMake for its build system.  A multi-stage build keeps the final image
# clean and lightweight.
#------------------------------------------------------------------------------

############################
# 1. Build stage
############################
FROM debian:stable-slim AS builder

#---------------------------------------------------------------------------
# Install all tooling required solely for the build.  Nothing in this block
# will be present in the final runtime image.
#---------------------------------------------------------------------------
RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive \
    apt-get install --yes --no-install-recommends \
        build-essential         \
        cmake                   \
        ninja-build             \
        pkg-config              \
        git                     \
        ca-certificates         \
        libssl-dev              \
        libpng-dev              \
        libjpeg-dev             \
        libavformat-dev         \
        libavcodec-dev          \
        libavutil-dev           \
        libswscale-dev          \
        && \
    rm -rf /var/lib/apt/lists/*

#---------------------------------------------------------------------------
# Copy the source tree and build the service.
#---------------------------------------------------------------------------
WORKDIR /opt/texture-service

# Copy only the files required for the build to leverage Docker layer caching.
COPY texture-service/CMakeLists.txt        ./
COPY texture-service/include               ./include
COPY texture-service/src                   ./src
COPY common                                 /opt/common            # shared library code
COPY third_party                            /opt/third_party
# Optionally, copy version metadata (git commit, tags).
ARG TEXTURE_VERSION=unknown
ENV TEXTURE_VERSION=${TEXTURE_VERSION}

# Configure & compile
RUN cmake -B build \
          -G Ninja \
          -DCMAKE_BUILD_TYPE=Release \
          -DTEXTURE_VERSION=${TEXTURE_VERSION} \
          -DCOMMON_DIR=/opt/common \
          -DTHIRD_PARTY_DIR=/opt/third_party \
          . && \
    cmake --build build --parallel

############################
# 2. Runtime stage
############################
FROM debian:stable-slim AS runtime

#---------------------------------------------------------------------------
# Security-hardened, minimal runtime environment.
#---------------------------------------------------------------------------
RUN set -eux; \
    apt-get update; \
    DEBIAN_FRONTEND=noninteractive \
    apt-get install --yes --no-install-recommends \
        libssl3         \
        libpng16-16     \
        libjpeg62-turbo \
        libavformat59   \
        libavcodec61    \
        libavutil57     \
        libswscale6     \
        && \
    rm -rf /var/lib/apt/lists/*

#---------------------------------------------------------------------------
# Metadata labels (OpenContainers spec)
#---------------------------------------------------------------------------
ARG VCS_REF=unknown
ARG BUILD_DATE
LABEL org.opencontainers.image.title="SynestheticCanvas Texture Service" \
      org.opencontainers.image.description="High-performance C service that synthesizes dynamic textures for SynestheticCanvas." \
      org.opencontainers.image.authors="SynestheticCanvas Team <dev@synestheticcanvas.io>" \
      org.opencontainers.image.url="https://synestheticcanvas.io" \
      org.opencontainers.image.documentation="https://docs.synestheticcanvas.io" \
      org.opencontainers.image.source="https://github.com/synestheticcanvas/texture-service" \
      org.opencontainers.image.version="${TEXTURE_VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.licenses="Apache-2.0"

#---------------------------------------------------------------------------
# Add a minimalistic, unprivileged user to enhance security.
#---------------------------------------------------------------------------
RUN set -eux; \
    groupadd --gid 10001 texture; \
    useradd --uid 10001 --gid texture --create-home --shell /usr/sbin/nologin texture

#---------------------------------------------------------------------------
# Copy compiled artifacts from builder stage.
#---------------------------------------------------------------------------
WORKDIR /opt/texture-service
COPY --from=builder /opt/texture-service/build/texture-service ./bin/texture-service
COPY --from=builder /opt/texture-service/build/texture-cli     ./bin/texture-cli     # optional admin CLI
COPY --from=builder /opt/texture-service/resources             ./resources
COPY --from=builder /opt/texture-service/conf/app.toml.example ./conf/app.toml

#---------------------------------------------------------------------------
# Reduce attack surface
#---------------------------------------------------------------------------
RUN chmod 0555 /opt/texture-service/bin/* && \
    chmod -R 0444 /opt/texture-service/resources && \
    chmod 0444 /opt/texture-service/conf/app.toml && \
    chown -R texture:texture /opt/texture-service

USER texture

#---------------------------------------------------------------------------
# Runtime configuration
#---------------------------------------------------------------------------
ENV TEXTURE_SERVICE_CONFIG=/opt/texture-service/conf/app.toml
ENV LOG_LEVEL=info

EXPOSE 7021/tcp

# Healthcheck probes if the service responds within 2 seconds.
HEALTHCHECK --interval=30s --timeout=2s --start-period=10s --retries=3 \
    CMD /opt/texture-service/bin/texture-cli --ping --host 127.0.0.1 --port 7021 || exit 1

#---------------------------------------------------------------------------
# Entrypoint wrapper adds minimal diagnostics.
#---------------------------------------------------------------------------
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/opt/texture-service/bin/texture-service", "--config", "/opt/texture-service/conf/app.toml"]

#------------------------------------------------------------------------------
# End Dockerfile
#------------------------------------------------------------------------------

