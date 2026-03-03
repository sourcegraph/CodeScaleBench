# SWE-bench Pro Task Environment
# Repo: protonmail/webclients

FROM ghcr.io/sg-evals/sweap-images:protonmail.webclients-protonmail__webclients-944adbfe06644be0789f59b78395bdd8567d8547

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh 2>/dev/null | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
ENTRYPOINT []
