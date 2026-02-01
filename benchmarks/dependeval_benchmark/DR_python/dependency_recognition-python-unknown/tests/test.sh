#!/bin/bash
set -e

# DependEval Dependency Recognition Test Script
# Evaluates exact match between predicted and ground truth dependencies

SUBMISSION_FILE="/workspace/submission.json"
GROUND_TRUTH_FILE="/workspace/ground_truth.json"
REWARD_FILE="/logs/verifier/reward.txt"

# Ensure output directory exists
mkdir -p /logs/verifier

# Check if submission exists
if [ ! -f "$SUBMISSION_FILE" ]; then
    echo "0.0" > "$REWARD_FILE"
    exit 0
fi

# Run evaluation
python3 /workspace/eval_scripts/eval_dr.py \
    --prediction "$SUBMISSION_FILE" \
    --ground_truth "$GROUND_TRUTH_FILE" \
    --output "$REWARD_FILE"

# Ensure we always exit 0 (Harbor requirement)
exit 0
