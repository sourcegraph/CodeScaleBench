#!/bin/bash
# Reward: checklist (0.0-1.0) — fault localization accuracy rubric
# Test script for lfl-acpi-207835: ACPI video backlight fault localization
# Ground truth: drivers/acpi/video_detect.c :: video_detect_dmi_table

set -e

cd /workspace

# Create log directories
mkdir -p /logs/verifier

# Check that the agent produced a result file
if [ ! -f "/workspace/fault_localization_result.json" ]; then
    echo "FAIL: /workspace/fault_localization_result.json not found"
    echo "0.0" > /logs/verifier/reward.txt
    echo ""
    echo "Tests completed - Score: 0.0 (no result file)"
    exit 0
fi

# Validate JSON
if ! python3 -c "import json; json.load(open('/workspace/fault_localization_result.json'))" 2>/dev/null; then
    echo "FAIL: fault_localization_result.json is not valid JSON"
    echo "0.0" > /logs/verifier/reward.txt
    echo ""
    echo "Tests completed - Score: 0.0 (invalid JSON)"
    exit 0
fi

# ── Scoring ──────────────────────────────────────────────
SCORE=0
MAX_SCORE=10

# Load ground truth from JSON
GT_FILE=$(python3 -c "import json; d=json.load(open('/tests/ground_truth.json')); print(d['buggy_files'][0])")
GT_METHODS=($(python3 -c "import json; d=json.load(open('/tests/ground_truth.json')); print(' '.join(d['buggy_functions']))"))


# Extract agent predictions
PREDICTED_FILES=$(python3 -c "
import json
data = json.load(open('/workspace/fault_localization_result.json'))
files = data.get('buggy_files', [])
for f in files:
    print(f)
" 2>/dev/null)

PREDICTED_METHODS=$(python3 -c "
import json
data = json.load(open('/workspace/fault_localization_result.json'))
methods = data.get('buggy_functions', [])
for m in methods:
    print(m)
" 2>/dev/null)

HAS_REASONING=$(python3 -c "
import json
data = json.load(open('/workspace/fault_localization_result.json'))
r = data.get('reasoning', '')
print('yes' if len(str(r)) > 10 else 'no')
" 2>/dev/null)

# Check 1: Result file has required fields (1 point)
HAS_FIELDS=$(python3 -c "
import json
data = json.load(open('/workspace/fault_localization_result.json'))
has = all(k in data for k in ['buggy_files', 'buggy_functions'])
print('yes' if has else 'no')
" 2>/dev/null)

if [ "$HAS_FIELDS" = "yes" ]; then
    echo "PASS: Result file has required fields"
    SCORE=$((SCORE + 1))
else
    echo "FAIL: Result file missing required fields (buggy_files, buggy_functions)"
fi

# Check 2: File-level localization - exact match (4 points)
FILE_MATCH="no"
while IFS= read -r pred_file; do
    # Normalize: strip leading /workspace/ or ./ if present
    pred_file=$(echo "$pred_file" | sed 's|^/workspace/||' | sed 's|^\./||')
    if [ "$pred_file" = "$GT_FILE" ]; then
        FILE_MATCH="yes"
        break
    fi
done <<< "$PREDICTED_FILES"

if [ "$FILE_MATCH" = "yes" ]; then
    echo "PASS: Correctly identified buggy file: $GT_FILE"
    SCORE=$((SCORE + 4))
else
    echo "FAIL: Did not identify buggy file: $GT_FILE"
    echo "  Predicted files: $PREDICTED_FILES"
fi

# Check 3: File-level localization - file in top-5 (1 point, only if exact match failed)
if [ "$FILE_MATCH" = "no" ]; then
    FILE_COUNT=0
    while IFS= read -r pred_file; do
        pred_file=$(echo "$pred_file" | sed 's|^/workspace/||' | sed 's|^\./||')
        FILE_COUNT=$((FILE_COUNT + 1))
        if [ "$pred_file" = "$GT_FILE" ] && [ "$FILE_COUNT" -le 5 ]; then
            echo "PASS: Buggy file found in top-5 predictions"
            SCORE=$((SCORE + 1))
            break
        fi
    done <<< "$PREDICTED_FILES"
fi

# Check 4: Method-level localization (3 points)
METHOD_MATCH="no"
for gt_method in "${GT_METHODS[@]}"; do
    while IFS= read -r pred_method; do
        if [ "$pred_method" = "$gt_method" ]; then
            METHOD_MATCH="yes"
            break 2
        fi
    done <<< "$PREDICTED_METHODS"
done

if [ "$METHOD_MATCH" = "yes" ]; then
    echo "PASS: Correctly identified buggy function/struct"
    SCORE=$((SCORE + 3))
else
    echo "FAIL: Did not identify buggy function/struct: ${GT_METHODS[*]}"
    echo "  Predicted methods: $PREDICTED_METHODS"
fi

# Check 5: Reasoning provided (1 point)
if [ "$HAS_REASONING" = "yes" ]; then
    echo "PASS: Reasoning provided"
    SCORE=$((SCORE + 1))
else
    echo "FAIL: No reasoning provided"
fi

# Check 6: Confidence score provided and valid (1 point)
HAS_CONFIDENCE=$(python3 -c "
import json
data = json.load(open('/workspace/fault_localization_result.json'))
c = data.get('confidence', None)
print('yes' if isinstance(c, (int, float)) and 0 <= c <= 1 else 'no')
" 2>/dev/null)

if [ "$HAS_CONFIDENCE" = "yes" ]; then
    echo "PASS: Valid confidence score provided"
    SCORE=$((SCORE + 1))
else
    echo "FAIL: Missing or invalid confidence score (expected 0.0-1.0)"
fi

# Convert to decimal score (0.0 - 1.0)
FINAL_SCORE=$(awk "BEGIN {printf \"%.1f\", $SCORE / $MAX_SCORE}")

echo "$FINAL_SCORE" > /logs/verifier/reward.txt
echo ""
echo "Tests completed - Score: $FINAL_SCORE (${SCORE}/${MAX_SCORE} checks passed)"
