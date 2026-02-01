#!/bin/bash
set -e

TRAJECTORY_PATH="${TRAJECTORY_PATH:-/logs/trajectory.jsonl}"
OUTPUT_PATH="/logs/tac_result.json"

if [ ! -f "$TRAJECTORY_PATH" ]; then
    echo '[]' > "$TRAJECTORY_PATH"
fi

echo "Running TAC evaluator for sde-write-a-unit-test-for-search_file-function..."
cd /utils

DECRYPTION_KEY="${DECRYPTION_KEY:-theagentcompany is all you need}" \
python_default /utils/eval.py \
    --trajectory_path "$TRAJECTORY_PATH" \
    --output_path "$OUTPUT_PATH" \
    2>&1 || {
    echo '{"score": 0, "checkpoints": [], "error": "Evaluator failed"}' > "$OUTPUT_PATH"
}

if [ -f "$OUTPUT_PATH" ]; then
    SCORE=$(python3 -c "import json; print(json.load(open('$OUTPUT_PATH')).get('score', 0))" 2>/dev/null || echo "0")
    echo "TAC Score: $SCORE"
    cp "$OUTPUT_PATH" /logs/reward.json 2>/dev/null || true
    
    if [ "$SCORE" != "0" ] && [ -n "$SCORE" ]; then
        exit 0
    else
        exit 1
    fi
else
    exit 1
fi
