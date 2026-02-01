#!/bin/bash
# PRDBench Verification Script
# Task: {id}
# Title: {title}

set -uo pipefail

echo "=== PRDBench Verifier ==="
echo "Task ID: {id}"

# Create output directories
mkdir -p /logs/verifier

# Activate conda environment if available
if [ -f /opt/conda/etc/profile.d/conda.sh ]; then
    source /opt/conda/etc/profile.d/conda.sh
    conda activate prdbench 2>/dev/null || true
fi

# Check for ground truth
if [ ! -f /tests/ground_truth.json ]; then
    echo "ERROR: ground_truth.json not found"
    echo '{"score": 0.0, "error": "Missing ground truth"}' > /logs/verifier/reward.json
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

# Look for test results in common locations
TEST_RESULTS=""
for path in /workspace/test_results.json /workspace/project/test_results.json /logs/test_results.json /app/test_results.json; do
    if [ -f "$path" ]; then
        TEST_RESULTS="$path"
        break
    fi
done

echo "Test results file: $TEST_RESULTS"

# Run Python verifier to evaluate against criteria
python3 /tests/verify.py \
    --test-results "$TEST_RESULTS" \
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
