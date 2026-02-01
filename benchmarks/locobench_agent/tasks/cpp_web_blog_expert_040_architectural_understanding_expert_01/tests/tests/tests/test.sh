#!/bin/bash
# LoCoBench-Agent Verification Script
# Evaluates agent solution against ground truth using semantic similarity

set -uo pipefail

echo "=== LoCoBench-Agent Verifier ==="
echo "Task ID: cpp_web_blog_expert_040_architectural_understanding_expert_01"
echo "Category: architectural_understanding"

# Create verifier output directory
mkdir -p /logs/verifier

# Check for ground truth
if [ ! -f /tests/ground_truth.json ]; then
    echo "ERROR: ground_truth.json not found"
    echo '{"score": 0.0, "error": "Missing ground truth"}' > /logs/verifier/reward.json
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

# Check for solution file (in mounted volume for persistence)
SOLUTION_FILE="/logs/agent/solution.md"
if [ ! -f "$SOLUTION_FILE" ]; then
    # Fallback to /app/solution.md for backwards compatibility
    SOLUTION_FILE="/app/solution.md"
    if [ ! -f "$SOLUTION_FILE" ]; then
        echo "ERROR: Agent did not create solution.md"
        echo '{"score": 0.0, "error": "No solution file created"}' > /logs/verifier/reward.json
        echo "0.0" > /logs/verifier/reward.txt
        exit 0
    fi
fi

echo "Solution file found: $SOLUTION_FILE"
echo "Running verification..."

# Run Python verifier
python3 /tests/verify.py \
    --solution "$SOLUTION_FILE" \
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
