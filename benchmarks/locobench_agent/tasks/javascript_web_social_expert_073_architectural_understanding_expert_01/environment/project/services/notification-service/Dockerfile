# ------------------------------------------------------------
# PulseLearn Campus Hub – Notification Service
# Dockerfile (multi-stage, production-ready)
# ------------------------------------------------------------
# This image compiles TypeScript sources, runs unit-tests, and
# ships a minimal, non-root runtime layer for the notification
# micro-service.
# ------------------------------------------------------------

# -------------------------------------------------------------------
# STAGE 1 – Builder
# -------------------------------------------------------------------
FROM node:20-slim AS builder

# Build-time metadata
ARG BUILD_DATE
ARG VCS_REF
LABEL org.opencontainers.image.title="PulseLearn Notification Service" \
      org.opencontainers.image.description="Real-time notification micro-service for PulseLearn Campus Hub" \
      org.opencontainers.image.vendor="PulseLearn" \
      org.opencontainers.image.url="https://github.com/pulselearn/campus-hub" \
      org.opencontainers.image.source="https://github.com/pulselearn/campus-hub/services/notification-service" \
      org.opencontainers.image.created=$BUILD_DATE \
      org.opencontainers.image.revision=$VCS_REF

# Avoid root user during build to prevent accidental permission issues
USER node

WORKDIR /usr/src/app

# Copy dependency manifests first (leverages Docker layer cache)
COPY --chown=node:node package.json package-lock.json* tsconfig.json ./

# Install ONLY production deps to cache layer efficiently
RUN npm ci --ignore-scripts --omit=dev

# Install remaining devDeps needed for compilation & tests
RUN npm install --ignore-scripts

# Copy full source + Prisma schema
COPY --chown=node:node src ./src
COPY --chown=node:node prisma ./prisma

# Generate Prisma client & compile TypeScript
RUN npx prisma generate --schema=./prisma/schema.prisma \
 && npm run build

# Run unit tests; set RUN_TESTS=false at build-time to skip
ARG RUN_TESTS=true
RUN if [ "$RUN_TESTS" = "true" ]; then npm test -- --runInBand; fi

# -------------------------------------------------------------------
# STAGE 2 – Runtime
# -------------------------------------------------------------------
FROM node:20-alpine AS runtime

# Switch to non-root user
USER node

WORKDIR /home/node/app

# Copy production node_modules and compiled sources
COPY --from=builder /usr/src/app/node_modules ./node_modules
COPY --from=builder /usr/src/app/dist ./dist
COPY --from=builder /usr/src/app/package.json ./

# Set minimal environment variables (override in Kubernetes / Docker-Compose)
ENV NODE_ENV=production \
    PORT=4005 \
    LOG_LEVEL=info

# Document service port
EXPOSE 4005

# Healthcheck calls lightweight /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:${PORT}/health || exit 1

# Launch service
CMD ["node", "./dist/index.js"]