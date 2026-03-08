# SWE-bench Pro Task Environment
# Instance: instance_internetarchive__openlibrary-92db3454aeaa02f89b4cdbc3103f7e95c9759f92-v2c55207218fb8a0138425cbf7d9675272e240b90
# Repo: internetarchive/openlibrary

FROM jefzda/sweap-images:internetarchive.openlibrary-internetarchive__openlibrary-92db3454aeaa02f89b4cdbc3103f7e95c9759f92-v2c55207218fb8a0138425cbf7d967

# Pre-install Node.js 22 + Claude Code at build time.
# Harbor's install.sh fails on this image (NodeSource GPG needs /dev/tty)
# but if claude is already on PATH, /tmp/claude_run.sh finds it.
RUN curl -fsSL https://nodejs.org/dist/v22.14.0/node-v22.14.0-linux-x64.tar.gz \
    | tar -xz -C /usr/local --strip-components=1 \
    && node --version && npm --version \
    && npm install -g @anthropic-ai/claude-code@latest \
    && which claude && claude --version

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories for Harbor
RUN mkdir -p /logs /workspace

# SWE-bench Pro images have the repository at /app, not /testbed
WORKDIR /app

# Override the default entrypoint to work with Harbor's docker-compose
# (The base image has ENTRYPOINT ["/bin/bash"] which doesn't work with Harbor's command format)
ENTRYPOINT []
