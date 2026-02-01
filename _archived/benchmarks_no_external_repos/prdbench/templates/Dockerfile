FROM continuumio/miniconda3:latest

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    jq \
    nginx \
    supervisor \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Create conda environment with common dependencies
RUN conda create -n prdbench python=3.11 -y && \
    conda clean -afy

# Activate conda environment by default
SHELL ["/bin/bash", "-c"]
ENV PATH /opt/conda/envs/prdbench/bin:$PATH

# Install common Python packages in conda environment
RUN /opt/conda/envs/prdbench/bin/pip install --no-cache-dir \
    flask \
    fastapi \
    uvicorn \
    django \
    pytest \
    requests \
    sqlalchemy \
    redis \
    celery \
    pydantic

# Create working directories
RUN mkdir -p /app /logs /workspace /tests /config

# Multi-port configuration for services
# Default ports: 3000 (frontend), 5000 (backend API), 8000 (main app), 6379 (redis)
EXPOSE 3000 5000 8000 6379

# Supervisor configuration for multi-service management
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf 2>/dev/null || true

# Set up workspace
WORKDIR /workspace

# Copy project files
COPY project /workspace/project 2>/dev/null || true

# Entry point that activates conda environment
RUN echo '#!/bin/bash' > /entrypoint.sh && \
    echo 'source /opt/conda/etc/profile.d/conda.sh' >> /entrypoint.sh && \
    echo 'conda activate prdbench' >> /entrypoint.sh && \
    echo 'exec "$@"' >> /entrypoint.sh && \
    chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["/bin/bash"]
