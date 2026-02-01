FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    git curl \
    && rm -rf /var/lib/apt/lists/*

# Clone repository at specific commit
RUN git clone https://github.com/{repository}.git /app/repo && \
    cd /app/repo && \
    git checkout {commit}

# Install Python dependencies for verification (if needed)
RUN pip install --no-cache-dir -q \
    tree-sitter==0.20.1 \
    python-dotenv

WORKDIR /app
