#!/bin/bash
# eval.sh — MCP-unique benchmark evaluator for CCX-onboard-050-ds
# Exit-code-first (SWE-Factory pattern):
#   exit 0 — agent produced useful output (composite score > 0)
#   exit 1 — total failure (composite score == 0 or missing answer)
#
# Writes /logs/verifier/reward.txt with the composite score [0.0, 1.0]
# Rubric judge (criteria.json) is supplementary — not used in this script.

set -euo pipefail

TASK_ID="CCX-onboard-050-ds"
ANSWER_PATH="/workspace/answer.json"
TASK_SPEC_PATH="/tests/task_spec.json"
ORACLE_CHECKS="/tests/oracle_checks.py"
REWARD_PATH="/logs/verifier/reward.txt"

mkdir -p /logs/verifier

echo "=== CCX-onboard-050-ds evaluator ==="
echo "Task spec: $TASK_SPEC_PATH"
echo "Answer:    $ANSWER_PATH"
echo ""

# sg_only mode guard: restore full repo if verifier wrapper exists
if [ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ]; then
    echo "sg_only mode: sourcing verifier wrapper..."
    source /tests/sgonly_verifier_wrapper.sh
fi

# Verify answer file exists
if [ ! -f "$ANSWER_PATH" ]; then
    echo "ERROR: answer.json not found at $ANSWER_PATH"
    echo "0.0" > "$REWARD_PATH"
    exit 1
fi

# Validate answer is valid JSON
if ! python3 -c "import json; json.load(open('$ANSWER_PATH'))" 2>/dev/null; then
    echo "ERROR: answer.json is not valid JSON"
    echo "0.0" > "$REWARD_PATH"
    exit 1
fi

echo "answer.json found and valid JSON"

# Run oracle checks
if [ ! -f "$ORACLE_CHECKS" ]; then
    echo "ERROR: oracle_checks.py not found at $ORACLE_CHECKS"
    echo "0.0" > "$REWARD_PATH"
    exit 1
fi

echo "Running oracle checks..."
SCORE=$(python3 "$ORACLE_CHECKS" --answer "$ANSWER_PATH" --spec "$TASK_SPEC_PATH" --verbose 2>&1 | tee /dev/stderr | tail -1) || true

# Validate score is a number
if ! echo "$SCORE" | python3 -c "import sys; float(sys.stdin.read().strip())" 2>/dev/null; then
    echo "ERROR: oracle_checks.py did not return a valid score: $SCORE"
    echo "0.0" > "$REWARD_PATH"
    exit 1
fi

echo ""
echo "Composite score: $SCORE"
echo "$SCORE" > "$REWARD_PATH"

# Exit based on score (SWE-Factory exit-code-first pattern)
python3 -c "import sys; sys.exit(0 if float('$SCORE') > 0 else 1)"
