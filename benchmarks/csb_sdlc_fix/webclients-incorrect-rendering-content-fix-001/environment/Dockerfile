# SWE-bench Pro Task Environment
# Repo: protonmail/webclients

FROM jefzda/sweap-images:protonmail.webclients-protonmail__webclients-2f66db85455f4b22a47ffd853738f679b439593c

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh 2>/dev/null | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
ENTRYPOINT []
