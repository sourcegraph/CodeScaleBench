# SWE-bench Pro Task Environment
# Instance: instance_protonmail__webclients-c6f65d205c401350a226bb005f42fac1754b0b5b
# Repo: protonmail/webclients

FROM jefzda/sweap-images:protonmail.webclients-protonmail__webclients-c6f65d205c401350a226bb005f42fac1754b0b5b

# Upgrade Node.js from v16 (base image) to v18 (required by Claude Code >= 2.1.37)
# Remove old Node, then install from Alpine 3.18+ repos (ships Node 18.x)
RUN apk del nodejs nodejs-current npm 2>/dev/null || true; \
    rm -f /usr/local/bin/node /usr/local/bin/npm /usr/local/bin/npx 2>/dev/null || true; \
    apk add --no-cache nodejs npm

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
