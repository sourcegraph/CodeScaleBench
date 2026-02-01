# syntax=docker/dockerfile:1.5

################################################################################
# EchoPulse – Real-Time Social Signal Processing Platform
# Dockerfile (multi-stage build)
#
# This image compiles the core EchoPulse service into a lean, distroless
# container ready for production workloads.
#
# Build:
#   docker build --build-arg VERSION=$(git describe --tags --always) \
#                --build-arg COMMIT_SHA=$(git rev-parse HEAD) \
#                --build-arg BUILD_TIMESTAMP=$(date -u +'%Y-%m-%dT%H:%M:%SZ') \
#                -t echopulse/echopulse:latest .
#
# Run:
#   docker run -p 8080:8080 -p 50051:50051 echopulse/echopulse:latest
################################################################################


############################
# Stage 0 – Build artifacts
############################
FROM golang:1.21-alpine AS builder

LABEL maintainer="EchoPulse Core Team <core@echopulse.ai>" \
      org.opencontainers.image.title="EchoPulse" \
      org.opencontainers.image.description="Real-Time Social Signal Processing Platform" \
      org.opencontainers.image.licenses="Apache-2.0"

# Build arguments injected at CI/CD time
ARG VERSION=dev
ARG COMMIT_SHA=unknown
ARG BUILD_TIMESTAMP=unknown

# Install system dependencies required for CGO, protobuf, and compilation cache
RUN apk add --no-cache \
        git \
        build-base \
        curl \
        protobuf \
        protobuf-dev

# Speed up builds by caching Go module & build cache layers
ENV GOOS=linux \
    GOARCH=amd64 \
    CGO_ENABLED=0 \
    GO111MODULE=on

WORKDIR /opt/echopulse

# 1. Download module dependencies first (leverages Docker layer caching)
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod \
    go mod download

# 2. Copy the rest of the source tree
COPY . .

# 3. (Optional) Generate gRPC / Protobuf stubs if Makefile provides the `proto` target
#    The mount points dramatically speed up iterative builds in modern Docker.
RUN --mount=type=cache,target=/root/.cache \
    --mount=type=cache,target=/go/pkg/mod \
    if [ -f Makefile ] && grep -qE '^proto:' Makefile ; then \
        make proto; \
    else \
        echo "No proto target found – skipping code generation"; \
    fi

# 4. Compile the primary service binary with reproducible flags
RUN --mount=type=cache,target=/root/.cache \
    --mount=type=cache,target=/go/build-cache \
    go build -trimpath -buildvcs=false \
        -ldflags="-s -w \
          -X 'echopulse/internal/buildinfo.version=${VERSION}' \
          -X 'echopulse/internal/buildinfo.commit=${COMMIT_SHA}' \
          -X 'echopulse/internal/buildinfo.date=${BUILD_TIMESTAMP}'" \
        -o /opt/bin/echopulse ./cmd/echopulse


##########################################
# Stage 1 – Final minimal runtime image
##########################################
FROM gcr.io/distroless/static:nonroot

# Expose public ports:
#   8080 – REST / metrics / profiling
#   50051 – gRPC API
EXPOSE 8080 50051

# Copy the statically-linked binary from the builder stage
COPY --from=builder /opt/bin/echopulse /app/echopulse

USER nonroot:nonroot
WORKDIR /app

# Basic health check invokes a lightweight sub-command; adapt as desired
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["/app/echopulse", "healthcheck"]

ENTRYPOINT ["/app/echopulse"]