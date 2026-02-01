# syntax=docker/dockerfile:1.4

###############################################################################
# CrowdPay Connect – Risk & Compliance Service
#
# A security-hardened, multi-stage Dockerfile that builds and packages the
# Python-based Risk & Compliance micro-service.  The image follows best
# practices:
#   * Uses an unprivileged user
#   * Separates build and runtime stages
#   * Pins the Python version
#   * Performs deterministic dependency installation
#   * Adds a lightweight health-check
###############################################################################

###############################################################################
#                               Builder Stage                                 #
###############################################################################
ARG PYTHON_VERSION=3.11

FROM python:${PYTHON_VERSION}-slim AS builder

# Install system build dependencies needed for pip to compile wheels.
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        git \
        curl && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Create and activate a virtual environment where dependencies will be cached.
ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv "${VIRTUAL_ENV}"
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# -----------------------------------------------------------------------------
# Copy dependency manifests first to take advantage of Docker layer caching.
# Supports either Poetry or traditional requirements.txt.
# -----------------------------------------------------------------------------
COPY risk_compliance_service/pyproject.toml risk_compliance_service/poetry.lock* ./  || true
COPY risk_compliance_service/requirements*.txt ./                              || true

# Upgrade pip and install Poetry (if required) without caching wheels.
RUN pip install --upgrade --no-cache-dir pip wheel setuptools

# If a Poetry project is detected, export an immutable requirements file.
RUN if [ -f "pyproject.toml" ] && [ -f "poetry.lock" ]; then \
        pip install --no-cache-dir poetry==1.7.* && \
        poetry export --without-hashes --format=requirements.txt \
            --output=requirements.txt && \
        pip uninstall --yes poetry; \
    fi

# Install Python dependencies into the virtual environment.
RUN if [ -f "requirements.txt" ]; then \
        pip install --no-cache-dir --upgrade -r requirements.txt ; \
    fi

###############################################################################
#                               Runtime Stage                                 #
###############################################################################
FROM python:${PYTHON_VERSION}-slim AS runtime

# Minimal OS packages required at runtime.
RUN --mount=type=cache,target=/var/cache/apt \
    apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates \
        netbase \
        curl \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Non-root user for application execution.
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Copy installed virtual environment from builder.
ENV VIRTUAL_ENV=/opt/venv
COPY --from=builder "${VIRTUAL_ENV}" "${VIRTUAL_ENV}"
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    LOG_LEVEL=info \
    PORT=8000

# Create application directory & copy source code.
WORKDIR /opt/app
COPY risk_compliance_service/ ./risk_compliance_service
# Ensure proper permissions.
RUN chown -R appuser:appgroup /opt/app

USER appuser

# Network configuration.
EXPOSE 8000

# Health check to verify service is responsive.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --silent --fail http://localhost:${PORT}/health || exit 1

# Entrypoint — uses gunicorn/uvicorn for async HTTP handling.
CMD ["uvicorn", "risk_compliance_service.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]