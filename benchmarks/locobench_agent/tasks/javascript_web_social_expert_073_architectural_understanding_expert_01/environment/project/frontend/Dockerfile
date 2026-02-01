# --------------------------------------------------------------------------
# PulseLearn Campus Hub – Front-End Dockerfile
# --------------------------------------------------------------------------
# This multi-stage Dockerfile builds a production-ready bundle of the
#   PulseLearn Campus Hub front-end (React / Vite) and serves it through
#   an optimized NGINX container.  It supports build-time configuration
#   for different environments (development, staging, production).
#
# Build arguments (override with `--build-arg`):
#   NODE_ENV            Node environment (default: production)
#   FRONTEND_ENV        Front-end environment (default: production)
#   PUBLIC_API_URL      Base URL of the back-end REST API
#   PUBLIC_WS_URL       Base URL of the websocket gateway
#   PUBLIC_SENTRY_DSN   Sentry DSN for error reporting
#
# Example:
#   docker build \
#     --build-arg PUBLIC_API_URL="https://api.pulselearn.io" \
#     --build-arg PUBLIC_WS_URL="wss://ws.pulselearn.io" \
#     -t pulselearn/web_social:latest .
# --------------------------------------------------------------------------

##############################
# 1. Build Stage
##############################
FROM node:20.10-alpine AS builder

# 1.1. Install system dependencies
RUN apk add --no-cache \
    git \
    openssh-client

# 1.2. Create app directory
WORKDIR /app

# 1.3. Copy package manifests first for better cache utilization
COPY frontend/package.json frontend/yarn.lock ./

# 1.4. Install production dependencies (omit dev dependencies for smaller layer)
RUN yarn install --frozen-lockfile --production

# 1.5. Copy application source
COPY frontend .

# 1.6. Inject build-time environment variables
ARG NODE_ENV=production
ARG FRONTEND_ENV=production
ARG PUBLIC_API_URL=https://api.pulselearn.local
ARG PUBLIC_WS_URL=wss://ws.pulselearn.local
ARG PUBLIC_SENTRY_DSN=

# All variables prefixed with VITE_* become public at runtime via Vite.
ENV NODE_ENV=${NODE_ENV} \
    VITE_APP_ENV=${FRONTEND_ENV} \
    VITE_API_URL=${PUBLIC_API_URL} \
    VITE_WS_URL=${PUBLIC_WS_URL} \
    VITE_SENTRY_DSN=${PUBLIC_SENTRY_DSN}

# 1.7. Build the static bundle
RUN yarn build

##############################
# 2. Runtime Stage
##############################
FROM nginx:1.25-alpine AS runtime

# 2.1. Copy build artifacts
COPY --from=builder /app/dist /usr/share/nginx/html

# 2.2. Remove default NGINX config & replace with custom
RUN rm /etc/nginx/conf.d/default.conf
COPY infra/docker/nginx/frontend.conf /etc/nginx/conf.d/frontend.conf

# 2.3. Make sure the static files are served with optimal compression
#       Brotli pre-compression significantly reduces payload size.
RUN apk add --no-cache brotli && \
    find /usr/share/nginx/html -type f -name '*.js' -o -name '*.css' | \
    xargs brotli -f --best && \
    find /usr/share/nginx/html -type f -name '*.js' -o -name '*.css' | \
    xargs gzip -f -9

# 2.4. Expose HTTP port
EXPOSE 80

# 2.5. Health check endpoint hits NGINX stub_status which is enabled
#       in `frontend.conf`.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s CMD \
  wget --no-verbose --tries=1 --spider http://localhost/healthz || exit 1

# 2.6. Non-root runtime (best practice)
RUN addgroup -g 10001 -S pulselrn && \
    adduser -S pulselrn -u 10001 -G pulselrn
USER pulselrn

# 2.7. Launch!
CMD ["nginx", "-g", "daemon off;"]

##############################
# 3. Development Convenience
##############################
# A quick way to start a dev server without docker-compose:
#
#   docker build --target builder -t pulselearn/web_social:dev .
#   docker run --rm -it -p 5173:5173 \
#       -e VITE_API_URL=http://localhost:8080 \
#       -e VITE_WS_URL=ws://localhost:8081 \
#       pulselearn/web_social:dev yarn dev
#
# The above allows hot-reloading against a locally running back-end.
##############################