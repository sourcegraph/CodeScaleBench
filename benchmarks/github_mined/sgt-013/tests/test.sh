#!/bin/bash
set -e

# Create logs directory
mkdir -p /logs/verifier
PRE_FIX_REV="9976b77abbb6e920684f899c539101e4b412f911"

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
