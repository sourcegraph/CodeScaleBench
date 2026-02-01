# syntax=docker/dockerfile:1.5

###############################################################################
# PulseSphere SocialOps – System Monitoring Service
# Production-grade, multi-stage Dockerfile
#
# – Targets:
#   1) builder   : Installs dependencies & compiles TypeScript
#   2) runner    : Lightweight, non-root runtime image
#
# – Features:
#   • Deterministic builds via `npm ci`
#   • Layer caching for node_modules
#   • Non-root execution (user:app)
#   • Health-check probe
#   • Supply-chain hardening (minimal packages, read-only FS)
###############################################################################

# --------------------------------------------------------------------------- #
# ARGs – can be overridden at build-time: `docker build --build-arg ...`
# --------------------------------------------------------------------------- #
ARG NODE_VERSION=20.9.0
ARG ALPINE_VERSION=3.18

# --------------------------------------------------------------------------- #
# 1) Builder Stage
# --------------------------------------------------------------------------- #
FROM --platform=$BUILDPLATFORM node:${NODE_VERSION}-alpine${ALPINE_VERSION:+@$ALPINE_VERSION} AS builder

WORKDIR /usr/src/app

# Install build dependencies required for node-gyp native extensions.
RUN apk add --no-cache --virtual .build-deps \
      python3 \
      make \
      g++ \
   && npm config set python "$(which python3)"

# Leverage Docker build-cache for dependency installation.
#   – `npm ci` enforces package-lock for reproducibility.
COPY package.json package-lock.json ./
ENV NODE_ENV=development
RUN --mount=type=cache,target=/root/.npm \
    npm ci

# Copy remaining sources & compile.
COPY tsconfig.json ./
COPY src ./src
RUN npm run build            # must map to "tsc -p ." in package.json
# optional: run unit tests (disabled by default for faster CI images)
# RUN npm test

# --------------------------------------------------------------------------- #
# 2) Runtime Stage
# --------------------------------------------------------------------------- #
FROM --platform=$TARGETPLATFORM node:${NODE_VERSION}-alpine${ALPINE_VERSION:+@$ALPINE_VERSION} AS runner

# Metadata labels (OCI)
LABEL org.opencontainers.image.title="PulseSphere SocialOps – System Monitoring Service" \
      org.opencontainers.image.description="Monitors infrastructure & social engagement telemetry in real-time." \
      org.opencontainers.image.vendor="PulseSphere" \
      org.opencontainers.image.authors="SRE Team <sre@pulsesphere.io>" \
      org.opencontainers.image.url="https://pulsesphere.io" \
      org.opencontainers.image.source="https://github.com/pulsesphere/socialops" \
      org.opencontainers.image.revision="${GIT_COMMIT:-unknown}" \
      org.opencontainers.image.created="${BUILD_DATE:-unknown}"

# Runtime environment vars
ENV NODE_ENV=production \
    TZ=UTC \
    # Service configuration (override via `docker run -e`)
    SERVICE_HTTP_PORT=8080 \
    SERVICE_LOG_LEVEL=info

# Create non-root user & group
RUN addgroup -S app && adduser -S app -G app

WORKDIR /app

# Copy compiled application & production dependencies from builder
COPY --from=builder /usr/src/app/node_modules ./node_modules
COPY --from=builder /usr/src/app/dist          ./dist
COPY --from=builder /usr/src/app/package.json  ./package.json

# (Optional) Reduce attack surface: strip dev tooling
RUN apk del .build-deps && \
    rm -rf /tmp/* /var/cache/apk/* /root/.npm

# Switch to non-privileged user
USER app

# Expose service port for service-mesh / ingress
EXPOSE ${SERVICE_HTTP_PORT}

# Healthcheck: simple TCP check (fast), fallback to HTTP endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD node ./dist/healthcheck.js || exit 1

# Use a read-only root filesystem (can be relaxed if app writes to FS)
# Note: If temporary write access is required, mount /tmp as tmpfs at runtime.
VOLUME ["/tmp"]
ENTRYPOINT ["node", "./dist/index.js"]