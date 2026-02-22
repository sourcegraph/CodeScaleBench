#!/bin/bash
# Reward: diff_similarity (0.0-1.0) — diff match to expected patch

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh
# Artifact mode: parse answer.json, extract analysis text, apply diffs
if [ -f /tmp/.artifact_only_mode ] && [ -f /tests/answer_json_verifier_lib.sh ]; then
    source /tests/answer_json_verifier_lib.sh
fi

set -eo pipefail
mkdir -p /logs/verifier
cd "${VERIFY_REPO:-/workspace}"
git config --global --add safe.directory /workspace 2>/dev/null || true
PRE_FIX_REV="5811a8d7da873dd699ff6687092c225caffcf1bb"
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
