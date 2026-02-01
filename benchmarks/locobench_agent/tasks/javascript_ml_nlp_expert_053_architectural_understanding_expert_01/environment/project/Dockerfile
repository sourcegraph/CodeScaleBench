# syntax=docker/dockerfile:1

##################################################################################################
#  AgoraPulse: Real-Time Social Signal Intelligence (ml_nlp)
#
#  Multi-stage Dockerfile that builds, tests, and ships a production-ready image capable of:
#      • Running the full TypeScript/Node.js event-driven core
#      • Bridging to optional Python-based model micro-services
#      • Exposing OpenTelemetry traces and Prometheus metrics
#      • Executing as a non-root user in an ultra-slim runtime layer
#
#  Build examples:
#      docker build -t agorapulse/ml-nlp:latest .
#      docker build --build-arg ENABLE_GPU=true --target runtime -t agorapulse/ml-nlp:gpu .
##################################################################################################

############################
# 1️⃣  Base — common metals
############################
FROM node:18-alpine AS base
LABEL stage=base

# Essential build & runtime packages.
RUN apk add --no-cache --virtual .build-deps \
        git \
        python3 \
        py3-pip \
        build-base \
        bash \
        curl

# Upgrade pip once per layer to keep cache efficient.
RUN pip3 install --no-cache-dir --upgrade pip

# Create a non-root user to drop privileges later.
RUN adduser -D -H -u 10001 appuser

WORKDIR /workspace

# Set sane defaults; they can be overridden at run-time.
ENV NODE_ENV=production \
    TZ=UTC \
    HOME=/home/appuser \
    # OpenTelemetry default target
    OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317 \
    # npm hygiene
    npm_config_fund=false \
    npm_config_audit=false \
    npm_config_progress=false

############################
# 2️⃣  Dependencies cache
############################
FROM base AS deps
LABEL stage=deps

# Copy manifests first to leverage Docker layer-cache.
COPY package.json package-lock.json tsconfig.json ./

RUN --mount=type=cache,target=/root/.npm \
    npm ci --ignore-scripts --include=dev

############################
# 3️⃣  Build & Test
############################
FROM deps AS builder
LABEL stage=builder

# Copy application source.
COPY . .

# Transpile TypeScript -> JavaScript (dist/).
RUN npm run build

# Lint & Unit-test to fail fast during CI/CD.
RUN npm run lint && npm test -- --ci --reporters=default

############################
# 4️⃣  Runtime — slim & secure
############################
FROM base AS runtime
LABEL stage=runtime \
      org.opencontainers.image.title="AgoraPulse – Real-Time Social Signal Intelligence" \
      org.opencontainers.image.description="Event-driven ML/NLP platform that converts raw social signals into actionable insights." \
      org.opencontainers.image.authors="AgoraPulse Engineering <engineering@agorapulse.ai>" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.source="https://github.com/agorapulse/ml_nlp"

# Optional GPU-enabled inference workers.
ARG ENABLE_GPU=false
ENV ENABLE_GPU=${ENABLE_GPU}

# Switch to non-root user early.
USER appuser
WORKDIR /app

# Production dependencies only.
COPY --chown=appuser --from=deps /workspace/node_modules ./node_modules

# Compiled sources.
COPY --chown=appuser --from=builder /workspace/dist ./dist
COPY --chown=appuser package.json ./

# Conditional Python ML stack (installed only if --build-arg ENABLE_GPU=true is provided).
RUN if [ "$ENABLE_GPU" = "true" ]; then \
        pip3 install --no-cache-dir torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cu118 && \
        pip3 install --no-cache-dir transformers==4.*; \
    fi

# Expose service & metrics ports.
EXPOSE 8080 9090

# Container health-check.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "require('http').get('http://localhost:8080/health', res => process.exit(res.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))"

# Default runtime command.
CMD ["node", "dist/index.js"]

##################################################################################################
#  End of File
##################################################################################################