# syntax=docker/dockerfile:1.4

#######################################################################
# PulseLearn Campus Hub – Course Service Dockerfile
#
# Uses a multi-stage build to keep the final image as small and secure
# as possible. The service is written in TypeScript, compiled to JS
# during the build, and runs as a non-root user in production.
#######################################################################

############################
# 1) Base image definition #
############################
FROM node:20-alpine AS base

# Common runtime arguments
ARG NODE_ENV=production
ENV NODE_ENV=${NODE_ENV}

# Set a consistent working directory
WORKDIR /usr/src/app

# Install tini (for proper signal handling) and dumb-init fallback
RUN apk add --no-cache tini

# Use tini as the entrypoint for all subsequent stages
ENTRYPOINT ["/sbin/tini", "--"]

############################
# 2) Dependency installation
#    (only production deps) #
############################
FROM base AS deps

# Install build tooling required by native addons
RUN apk add --no-cache --virtual .gyp python3 make g++

# Install only package.json first to leverage Docker layer caching
COPY package*.json ./

# Install prod dependencies (omit dev to shrink final image)
RUN npm ci --omit=dev

############################
# 3) Builder stage         #
#    (compile TypeScript)  #
############################
FROM node:20-alpine AS builder
WORKDIR /usr/src/app

# Native build tooling
RUN apk add --no-cache --virtual .gyp python3 make g++

# Copy the full source tree
COPY . .

# Install full dependency tree inc. devDeps
RUN npm ci

# Type-check and compile the codebase
RUN npm run build

############################
# 4) Production runtime    #
############################
FROM base AS production

# Create an unprivileged user to drop root
RUN addgroup -S plearn && adduser -S plearn -G plearn

# Copy prod dependencies
COPY --from=deps /usr/src/app/node_modules ./node_modules

# Copy compiled Javascript bundle
COPY --from=builder /usr/src/app/dist ./dist

# Copy any runtime assets (example: SSL certs, GraphQL schema, etc.)
COPY --from=builder /usr/src/app/config ./config

# Expose HTTP port
EXPOSE 8080

# Optional metadata (helps with DevOps asset management)
LABEL org.opencontainers.image.title="PulseLearn Course Service" \
      org.opencontainers.image.description="Handles course lifecycle, metadata, and curriculum workflows for PulseLearn Campus Hub." \
      org.opencontainers.image.version="1.0.0" \
      maintainer="PulseLearn Engineering <engineering@pulselearn.io>" \
      org.opencontainers.image.licenses="Apache-2.0"

# Health check – hits the lightweight /health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:8080/health || exit 1

# Run as non-root user
USER plearn

# Default command
CMD ["node", "dist/main.js"]