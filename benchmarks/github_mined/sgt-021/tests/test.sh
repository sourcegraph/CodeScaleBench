#!/bin/bash
set -e

# Create logs directory
mkdir -p /logs/verifier
PRE_FIX_REV="cbe1a35dbdfdc9b7490212bdd812f3e2f4ce9e2d"

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
