#!/bin/bash
set -e

# Create logs directory
mkdir -p /logs/verifier
PRE_FIX_REV="863edc787f5fa7950e0f3f86d4952641e1ef9c2c"

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
