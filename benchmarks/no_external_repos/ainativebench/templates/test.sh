#!/bin/bash
# AINativeBench Verification Script
# Task: {id}
# Benchmark: {benchmark_name}

set -uo pipefail

echo "=== AINativeBench Verifier ==="
echo "Task ID: {id}"
echo "Benchmark: {benchmark_name}"

# Create output directories
mkdir -p /logs/verifier

# Check for test_results directory (AINativeBench native output format)
TEST_RESULTS_DIR="/test_results"
if [ ! -d "$TEST_RESULTS_DIR" ]; then
    # Check alternative locations
    if [ -d "/app/test_results" ]; then
        TEST_RESULTS_DIR="/app/test_results"
    elif [ -d "/workspace/test_results" ]; then
        TEST_RESULTS_DIR="/workspace/test_results"
    fi
fi

# Check for ground truth
if [ ! -f /tests/ground_truth.json ]; then
    echo "ERROR: ground_truth.json not found"
    echo '{"score": 0.0, "error": "Missing ground truth"}' > /logs/verifier/reward.json
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

echo "Looking for test results in: $TEST_RESULTS_DIR"

# Run Python verifier to parse test_results and generate reward.json
python3 /tests/verify.py \
    --test-results-dir "$TEST_RESULTS_DIR" \
    --ground-truth /tests/ground_truth.json \
    --output /logs/verifier/reward.json \
    2>&1 | tee /logs/verifier/verifier.log

# Extract score and write to reward.txt
if [ -f /logs/verifier/reward.json ]; then
    SCORE=$(python3 -c "import json; print(json.load(open('/logs/verifier/reward.json')).get('score', 0.0))" 2>/dev/null || echo "0.0")
    echo "$SCORE" > /logs/verifier/reward.txt
    echo "Verification complete. Score: $SCORE"
else
    echo "0.0" > /logs/verifier/reward.txt
    echo "Verification failed - no reward.json generated"
fi

# Always exit 0 for Harbor compatibility
exit 0
