#!/bin/bash
# Reward: diff_similarity (0.0-1.0) — diff match to expected patch
set -eo pipefail
mkdir -p /logs/verifier
cd /workspace
git config --global --add safe.directory /workspace 2>/dev/null || true
PRE_FIX_REV="e3e93c7107830c13f4139c3a62fda62c6b84bbf5"
python3 /tests/verify_diff.py \
    --expected /tests/expected.diff \
    --pre-fix-rev "$PRE_FIX_REV" \
    --output /logs/verifier/reward.json \
    2>&1 | tee /logs/verifier/verifier.log
REWARD=$(python3 -c "import json; print(json.load(open('/logs/verifier/reward.json')).get('reward', 0.0))" 2>/dev/null || echo "0.0")
echo "$REWARD" > /logs/verifier/reward.txt
echo "Final reward: $REWARD"
git diff "$PRE_FIX_REV" > /logs/verifier/agent.diff 2>/dev/null || true
git diff "$PRE_FIX_REV" --stat > /logs/verifier/diff.stat 2>/dev/null || true
exit 0
