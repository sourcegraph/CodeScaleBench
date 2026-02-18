#!/bin/bash
# Reward: ordering (0.0-1.0) — DependEval-style blended scoring
# Verifies transitive dependency ordering of evaluation.go imports

set -e

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh


cd /workspace

mkdir -p /logs/verifier

git config --global --add safe.directory /workspace 2>/dev/null || true

# Check if submission file exists
if [ ! -f /workspace/submission.json ]; then
    echo "No submission.json found"
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

# Validate JSON
if ! python3 -c "import json; json.load(open('/workspace/submission.json'))" 2>/dev/null; then
    echo "submission.json is not valid JSON"
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

echo "Running dep-discovery-001 evaluation..."

# Run DependEval-style ordering evaluation
python3 /tests/eval_scripts/eval_dr.py

echo ""
echo "[x] Evaluation completed - Score: $(cat /logs/verifier/reward.txt)"
