#!/bin/bash
set -e

# Install dependencies based on distro
if command -v apk &> /dev/null; then
    # Alpine Linux - use apk for nodejs/npm (nvm has musl compatibility issues)
    # Alpine 3.23+ provides Node.js 24.x which is compatible with claude-code
    apk add --no-cache curl bash nodejs npm
elif command -v apt-get &> /dev/null; then
    # Debian/Ubuntu - install Node.js 22 via NodeSource (more reliable than nvm in Docker)
    apt-get update
    apt-get install -y curl ca-certificates gnupg

    # Install Node.js 22.x via NodeSource
    mkdir -p /etc/apt/keyrings
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list
    apt-get update
    apt-get install -y nodejs
else
    echo "Unsupported distribution: No apk or apt-get package manager found." >&2
    exit 1
fi

npm -v


npm install -g @anthropic-ai/claude-code@latest


# Verify node and npm
node --version
npm --version

# Verify claude is installed and accessible
which claude
claude --version