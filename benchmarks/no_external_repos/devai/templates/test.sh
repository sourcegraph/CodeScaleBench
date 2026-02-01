#!/bin/bash
# DevAI Verification Script
# Task: {id}
# Domain: {domain}

set -uo pipefail

echo "=== DevAI Verifier ==="
echo "Task ID: {id}"
echo "Domain: {domain}"

# Create output directories
mkdir -p /logs/verifier

# Check for trajectory file
TRAJECTORY_FILE="/trajectory/trajectory.json"
if [ ! -f "$TRAJECTORY_FILE" ]; then
    # Check alternative locations
    if [ -f "/workspace/trajectory.json" ]; then
        TRAJECTORY_FILE="/workspace/trajectory.json"
    elif [ -f "/app/trajectory.json" ]; then
        TRAJECTORY_FILE="/app/trajectory.json"
    fi
fi

# Check for ground truth
if [ ! -f /tests/ground_truth.json ]; then
    echo "ERROR: ground_truth.json not found"
    echo '{"score": 0.0, "error": "Missing ground truth"}' > /logs/verifier/reward.json
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

echo "Trajectory file: $TRAJECTORY_FILE"

# Run Python verifier to validate trajectory and generate reward.json
python3 /tests/verify.py \
    --trajectory "$TRAJECTORY_FILE" \
    --schema /tests/trajectory-schema.json \
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
