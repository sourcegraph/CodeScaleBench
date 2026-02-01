#!/bin/bash
set -e

# Create logs directory
mkdir -p /logs/verifier
PRE_FIX_REV="a61b434dd46e951240ca6b9dd0e975f281c6d2a2"

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
