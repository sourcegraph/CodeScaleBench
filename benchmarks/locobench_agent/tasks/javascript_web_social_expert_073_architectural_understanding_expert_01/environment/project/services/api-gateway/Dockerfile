# ---------------------------------------------------------------------------
# PulseLearn Campus Hub – API Gateway (Node.js)
#
# Production-ready Dockerfile that builds a slim, secure container for the
# real-time API-Gateway service.  Implements a multi-stage build to:
#   1) install dependencies
#   2) transpile & bundle TypeScript (if present)
#   3) copy only the runtime artefacts into the final image
#
# Notes:
#   - tiny Alpine image keeps attack surface minimal
#   - USER non-root (node) runs service
#   - HEALTHCHECK wires readiness into orchestration platform (K8s / Docker Swarm)
#   - Caching layers (npm, tsc) dramatically cut CI/CD times
# ---------------------------------------------------------------------------

# syntax=docker/dockerfile:1.4

#############################
# 1. Base stage
#############################
FROM node:20-alpine AS base

LABEL org.opencontainers.image.title="PulseLearn API-Gateway"        \
      org.opencontainers.image.description="Reactive, event-driven edge gateway for PulseLearn Campus Hub" \
      org.opencontainers.image.version="1.0.0"                       \
      maintainer="PulseLearn DevOps <devops@pulselearn.io>"

ARG APP_DIR=/usr/src/app

# Environment defaults
ENV NODE_ENV=production \
    TZ=UTC \
    # Skip large optional binaries e.g. for Puppeteer
    PUPPETEER_SKIP_DOWNLOAD=1 \
    # Quieter npm output in CI
    NPM_CONFIG_LOGLEVEL=warn

WORKDIR ${APP_DIR}

# Install minimal system packages & create non-root user
RUN --mount=type=cache,target=/var/cache/apk \
    apk add --no-cache tini bash curl && \
    addgroup -S nodejs -g 1001 && \
    adduser  -S node   -u 1001 -G nodejs

#############################
# 2. Dependency stage
#############################
FROM base AS deps

# Copy manifests separately to leverage cache
COPY package*.json ./

# Install ONLY production deps, using a cached npm directory
RUN --mount=type=cache,target=/root/.npm \
    npm ci --omit=dev --ignore-scripts && \
    npm cache clean --force

#############################
# 3. Builder stage
#    (if project uses TypeScript/ESBuild/Babel)
#############################
FROM base AS builder
ENV NODE_ENV=development

# Re-use node_modules from deps
COPY --from=deps ${APP_DIR}/node_modules ./node_modules

# Copy source code
COPY tsconfig*.json ./
COPY src ./src

# Build application (adjust to project’s build script)
RUN --mount=type=cache,target=/root/.cache \
    npm run build

#############################
# 4. Production release stage
#############################
FROM base AS release

# Copy runtime artefacts
COPY --from=builder --chown=node:nodejs ${APP_DIR}/dist ./dist
COPY --from=deps    --chown=node:nodejs ${APP_DIR}/node_modules ./node_modules
COPY --chown=node:nodejs package*.json ./
COPY --chown=node:nodejs ./config ./config

# Extra safety: ensure only runtime deps are present
RUN npm prune --omit=dev --ignore-scripts && \
    chown -R node:nodejs ${APP_DIR}

# Switch to least-privileged user
USER node

# Documents exposed ports: 8080 = HTTP, 9229 = optional Node.js inspector
EXPOSE 8080 9229

# ————— Healthcheck —————
# Queries internal health endpoint; non-200 → unhealthy
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "require('http').get('http://localhost:8080/health', r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"

# ————— Entrypoint —————
ENTRYPOINT ["tini", "--"]
CMD ["node", "dist/main.js"]

# End of Dockerfile 🚀
