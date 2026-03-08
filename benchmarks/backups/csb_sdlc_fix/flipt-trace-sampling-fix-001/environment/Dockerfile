# SWE-bench Pro Task Environment
# Instance: instance_flipt-io__flipt-3d5a345f94c2adc8a0eaa102c189c08ad4c0f8e8
# Repo: flipt-io/flipt

FROM jefzda/sweap-images:flipt-io.flipt-flipt-io__flipt-3d5a345f94c2adc8a0eaa102c189c08ad4c0f8e8

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
