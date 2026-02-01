FROM python:3.10-slim

WORKDIR /workspace

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    wget \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies for evaluation
RUN pip install --no-cache-dir \
    networkx \
    pygments

# Copy evaluation scripts, ground truth, and code content
COPY eval_scripts/ /workspace/eval_scripts/
COPY ground_truth.json /workspace/ground_truth.json
COPY code_content.txt /workspace/code_content.txt

# Make evaluation scripts executable
RUN chmod +x /workspace/eval_scripts/*.py

# Set up output directory
RUN mkdir -p /logs/verifier

# Set default command
CMD ["/bin/bash"]
