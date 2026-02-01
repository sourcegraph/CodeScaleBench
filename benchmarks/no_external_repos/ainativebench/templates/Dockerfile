FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Create working directories
RUN mkdir -p /app /logs /workspace /tests /test_results

# Set up Python environment with uv
WORKDIR /app

# Copy project files (if any)
COPY project /app/project

CMD ["/bin/bash"]
