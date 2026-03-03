# SWE-bench Pro Task Environment
# Repo: gravitational/teleport

FROM jefzda/sweap-images:gravitational.teleport-gravitational__teleport-3ff75e29fb2153a2637fe7f83e49dc04b1c99c9f

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh 2>/dev/null | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
ENTRYPOINT []
