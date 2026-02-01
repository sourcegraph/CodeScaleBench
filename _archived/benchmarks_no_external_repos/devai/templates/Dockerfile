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

# Create working directories following DevAI workspace structure
# benchmark/workspaces/{AGENT_NAME}/{task_name}/
RUN mkdir -p /app /logs /workspace /tests /trajectory

# Set up Python environment with uv
WORKDIR /workspace

# Copy project files (if any)
COPY project /workspace/project

CMD ["/bin/bash"]
