# SWE-bench Pro Task Environment
# Instance: instance_flipt-io__flipt-9f8127f225a86245fa35dca4885c2daef824ee55
# Repo: flipt-io/flipt

FROM jefzda/sweap-images:flipt-io.flipt-flipt-io__flipt-9f8127f225a86245fa35dca4885c2daef824ee55

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
