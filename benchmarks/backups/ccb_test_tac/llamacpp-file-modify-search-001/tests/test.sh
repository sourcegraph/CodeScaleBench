#!/bin/bash
# Reward: checklist (0.0-1.0) — task-specific evaluation criteria
set -e

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh


TRAJECTORY_PATH="${TRAJECTORY_PATH:-/logs/trajectory.jsonl}"
OUTPUT_PATH="/logs/tac_result.json"

if [ ! -f "$TRAJECTORY_PATH" ]; then
    echo '[]' > "$TRAJECTORY_PATH"
fi

echo "Running TAC evaluator for sde-find-answer-in-codebase-2..."
cd /utils

# NOTE: init.sh intentionally SKIPPED during verification.
# init.sh resets RocketChat services, which destroys the agent's chat messages
# before eval.py can read them. The services are already running from the agent's
# session, so no re-initialization is needed for the verifier.
# if [ -f "/utils/init.sh" ]; then
#     SERVER_HOSTNAME="${TAC_SERVER_HOSTNAME:-localhost}" bash /utils/init.sh || true
# fi

DECRYPTION_KEY="${DECRYPTION_KEY:-theagentcompany is all you need}" \
python_default /utils/eval.py \
    --trajectory_path "$TRAJECTORY_PATH" \
    --result_path "$OUTPUT_PATH" \
    2>&1 || {
    echo '{"score": 0, "checkpoints": [], "error": "Evaluator failed"}' > "$OUTPUT_PATH"
}

mkdir -p /logs/verifier

if [ -f "$OUTPUT_PATH" ]; then
    SCORE=$(python3 -c "
import json
d = json.load(open('$OUTPUT_PATH'))
if 'final_score' in d:
    fs = d['final_score']
    total = fs.get('total', 0)
    print(round(fs['result'] / total, 4) if total > 0 else 0)
elif 'score' in d:
    print(d['score'])
else:
    print(0)
" 2>/dev/null || echo "0")
    echo "TAC Score: $SCORE"
    echo "$SCORE" > /logs/verifier/reward.txt
    cp "$OUTPUT_PATH" /logs/verifier/reward.json 2>/dev/null || true
    exit 0
else
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi
