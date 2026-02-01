# syntax=docker/dockerfile:1.5

###############################################################################
# PulseLearn Campus Hub – Auth Service Dockerfile
#
# This image is built in three stages:
#   1. deps    : Restore Node dependencies using npm ci for reproducibility.
#   2. builder : (optional) Compile TypeScript or transpile source, run tests.
#   3. runtime : Thin, production-ready image running as a non-root user with
#                strict security flags and a health-check.
###############################################################################

##############################
# 1. Dependency Restoration
##############################
FROM node:20-alpine AS deps

# Meta-data for traceability
LABEL org.opencontainers.image.title="PulseLearn Auth Service" \
      org.opencontainers.image.description="Authentication & Session service for PulseLearn Campus Hub" \
      org.opencontainers.image.vendor="PulseLearn" \
      org.opencontainers.image.authors="devops@pulselearn.io" \
      org.opencontainers.image.source="https://github.com/pulselearn/pulselearn-campus-hub" \
      org.opencontainers.image.version="0.1.0"

# Required packages for native node-gyp builds (e.g. bcrypt, argon2)
RUN apk add --no-cache --virtual .gyp \
      python3 \
      make \
      g++ \
      git

WORKDIR /srv/app

# Copy lock files first for efficient layer caching
COPY package.json package-lock.json* .npmrc* ./

# Install production dependencies. We keep devDependencies for builder stage.
RUN npm ci --ignore-scripts

##############################
# 2. Builder / Test stage
##############################
FROM node:20-alpine AS builder

# Install tini for proper PID-1 signal handling
RUN apk add --no-cache tini

ENV NODE_ENV=development

WORKDIR /srv/app

# ─── Copy dependency tree from previous layer
COPY --from=deps /srv/app/node_modules ./node_modules
COPY . .

# Optional: Transpile TypeScript ➜ JavaScript
# If project is JS only, this will be a no-op but harmless.
RUN if [ -f tsconfig.json ]; then npm run build; fi

# Run unit tests — fail build on test errors
RUN if [ -f ./package.json ]; then npm test --if-present; fi

##############################
# 3. Production Runtime
##############################
FROM node:20-alpine AS runtime

# Security hardening & minimal footprint
RUN apk add --no-cache tini dumb-init && \
    addgroup -g 1001 nonroot && \
    adduser  -D -G nonroot -u 1001 nonroot

ENV NODE_ENV=production \
    # Disable npm update notifications & analytics
    NPM_CONFIG_LOGLEVEL=error \
    NPM_CONFIG_AUDIT=false \
    NPM_CONFIG_FUND=false \
    # Timezone can be overridden at runtime
    TZ=UTC

WORKDIR /srv/app

# Copy only compiled/dist application and production dependencies
COPY --from=deps    /srv/app/node_modules ./node_modules
COPY --from=builder /srv/app/dist            ./dist
# Retain package.json for runtime env detection/tools
COPY package.json ./

USER nonroot

EXPOSE 8080

# Health check — hits lightweight endpoint exposed by Express/Koa/Fastify
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:8080/health || exit 1

ENTRYPOINT ["/sbin/dumb-init", "--"]

CMD ["node", "dist/index.js"]