#!/bin/bash
set -e

# Create logs directory
mkdir -p /logs/verifier
PRE_FIX_REV="76b8fdafad537579cd97b5ec2502c6ac3bc473e0"

# Run actual tests
echo "Running test command: make test"
if make test; then
    echo "✓ Tests passed"
    echo "1" > /logs/verifier/reward.txt
    exit 0
else
    echo "✗ Tests failed"
    echo "0" > /logs/verifier/reward.txt
    exit 1
fi
