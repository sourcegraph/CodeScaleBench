#!/bin/bash
set -e

# DependEval Repository Construction Test Script
# Evaluates call chain graph similarity using F1 score

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
python3 /workspace/eval_scripts/eval_rc.py \
    --prediction "$SUBMISSION_FILE" \
    --ground_truth "$GROUND_TRUTH_FILE" \
    --output "$REWARD_FILE"

# Ensure we always exit 0 (Harbor requirement)
exit 0
