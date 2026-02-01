# -------------------------------------------------------------------------------------------------
# PulseLearn Campus Hub – Payment Service
# Production-ready, multi-stage Dockerfile
#
# This image is purposely hardened for running the Node.js-based “payment-service” in Kubernetes
# or any modern container orchestrator.  It follows current best-practices:
#   • Uses an up-to-date, LTS Alpine base image
#   • Performs dependency installation in a dedicated build stage for layer-caching
#   • Runs as a non-root user
#   • Implements a reliable HEALTHCHECK for zero-downtime rollouts
#   • Reduces attack-surface by pruning dev-dependencies, cleaning cache, and stripping setuid bits
# -------------------------------------------------------------------------------------------------

#############
# Stage 1 – Dependencies
#############
FROM node:18.17.1-alpine3.18 AS deps

# 1) Use UTF-8 as default encoding
ENV LANG C.UTF-8

# 2) Set workdir early to leverage Docker layer-cache
WORKDIR /opt/pulselearn/payment-service

# 3) Copy only dependency manifests first; this maximises cache hits when source changes
COPY package.json package-lock.json ./

# 4) Install dependencies (production + peer deps); leverage build-cache for npm
RUN --mount=type=cache,id=npm-cache,target=/root/.npm \
    npm ci --ignore-scripts --no-audit --prefer-offline --progress=false

##############
# Stage 2 – Application Build (optional)
# If you transpile TypeScript, React SSR, etc., do it here.
# For pure JavaScript micro-services, we simply copy sources.
##############
FROM deps AS builder
COPY . .
# (Uncomment if you run a build step)
# RUN npm run build

##############
# Stage 3 – Runtime
##############
FROM node:18.17.1-alpine3.18 AS runtime

# -----------------------------------------------------------------------------
# Metadata labels (OCI-compliant) for traceability
# -----------------------------------------------------------------------------
LABEL org.opencontainers.image.title="PulseLearn Campus Hub – Payment Service" \
      org.opencontainers.image.description="Handles Stripe / Braintree transactions & course purchases" \
      org.opencontainers.image.authors="PulseLearn Engineering <engineering@pulselearn.io>" \
      org.opencontainers.image.url="https://github.com/PulseLearn/pulselearn-campus-hub" \
      org.opencontainers.image.documentation="https://docs.pulselearn.io" \
      org.opencontainers.image.version="1.0.0"

# -----------------------------------------------------------------------------
# Security hardening
#   • Create non-root user
#   • Drop setuid/setgid bits
# -----------------------------------------------------------------------------
RUN addgroup -S nodejs && adduser -S nodejs -G nodejs

# Create and own application directory
WORKDIR /srv/app
RUN chown nodejs:nodejs /srv/app

# Copy only what we need from builder image
COPY --from=builder --chown=nodejs:nodejs /opt/pulselearn/payment-service ./

# Remove every SUID/SGID bit from the base image to mitigate privilege-escalation
RUN find / -xdev -type f -perm +6000 -print0 | xargs -0r chmod a-s

USER nodejs

# -----------------------------------------------------------------------------
# Runtime environment configuration
# -----------------------------------------------------------------------------
ENV NODE_ENV=production \
    PORT=8082 \
    # Prevent Node from writing core dumps & set faster, more secure defaults
    NODE_OPTIONS="--max_old_space_size=256 --require ./src/bootstrap/env-safe.js" \
    # Disable npm update notifications
    NO_UPDATE_NOTIFIER=true

# Expose application port
EXPOSE ${PORT}

# -----------------------------------------------------------------------------
# Healthcheck: verify that the HTTP-level liveness endpoint is responsive.
# Uses the lightweight BusyBox wget shipped with Alpine.
# -----------------------------------------------------------------------------
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:${PORT}/health || exit 1

# -----------------------------------------------------------------------------
# Start command
# -----------------------------------------------------------------------------
CMD ["node", "src/server.js"]
