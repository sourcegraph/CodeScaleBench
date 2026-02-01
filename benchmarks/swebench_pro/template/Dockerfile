# SWE-bench Pro Task Environment
# Instance: {instance_id}
# Repo: {repo}

FROM {docker_image}

# Install uv for Python package management (if needed)
RUN curl -LsSf https://astral.sh/uv/0.7.13/install.sh | sh || true

# Create required directories
RUN mkdir -p /logs /workspace /tests

WORKDIR /app

# Copy test configuration
COPY tests/config.json /tests/config.json
COPY tests/test.sh /tests/test.sh
RUN chmod +x /tests/test.sh
