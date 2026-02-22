#!/bin/bash
# Reward: ir_checklist (0.0-1.0) — IR metrics + root cause identification for bug investigation
# Composite: 0.4 * task_quality + 0.3 * file_recall + 0.2 * file_precision + 0.1 * dep_accuracy
# Bonus: root_cause_mrr factored into task_quality

set -e

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh
# Artifact mode: parse answer.json, extract analysis text, apply diffs
if [ -f /tmp/.artifact_only_mode ] && [ -f /tests/answer_json_verifier_lib.sh ]; then
    source /tests/answer_json_verifier_lib.sh
fi

cd "${VERIFY_REPO:-/workspace}"
mkdir -p /logs/verifier

git config --global --add safe.directory /workspace 2>/dev/null || true

# ── Source shared verifier library ────────────────────────────────────────
source /tests/verifier_lib.sh

# ── Output check ─────────────────────────────────────────────────────────
SOLUTION_FILE="/logs/agent/solution.md"
# In artifact mode, populate expected output from answer.json analysis
if [ "${ARTIFACT_ONLY:-false}" = "true" ] && [ -f "${ANALYSIS_TEXT_FILE:-}" ]; then
    mkdir -p "/logs/agent"
    cp "$ANALYSIS_TEXT_FILE" "/logs/agent/solution.md"
    echo "[answer_json] Copied analysis text to /logs/agent/solution.md"
fi
if [ ! -f "$SOLUTION_FILE" ] || [ "$(wc -c < "$SOLUTION_FILE" 2>/dev/null || echo 0)" -lt 200 ]; then
    echo "No sufficient solution.md — agent did not produce analysis"
    echo "0.0" > /logs/verifier/reward.txt
    echo "[ ] Tests completed - Score: 0.0 (no output)"
    exit 0
fi

SOLUTION_SIZE=$(wc -c < "$SOLUTION_FILE")
echo "Solution file found ($SOLUTION_SIZE bytes)"

# ── IR metrics pipeline ──────────────────────────────────────────────────
run_ir_pipeline "$SOLUTION_FILE" "/tests/ground_truth.json" "/logs/verifier/ir_metrics.json"

# ── Task quality scoring ─────────────────────────────────────────────────
QUALITY_SCORE=0
QUALITY_MAX=10

# Check for required sections
if grep -qiE '^##\s+(Files Examined|Files Analyzed)' "$SOLUTION_FILE"; then
    QUALITY_SCORE=$((QUALITY_SCORE + 1))
    echo "[x] Has 'Files Examined' section"
fi

if grep -qiE '^##\s+(Dependency Chain|Call Chain)' "$SOLUTION_FILE"; then
    QUALITY_SCORE=$((QUALITY_SCORE + 1))
    echo "[x] Has 'Dependency Chain' section"
fi

if grep -qiE '^##\s+Root Cause' "$SOLUTION_FILE"; then
    QUALITY_SCORE=$((QUALITY_SCORE + 2))
    echo "[x] Has 'Root Cause' section"
else
    echo "[ ] Missing 'Root Cause' section"
fi

if grep -qiE '^##\s+Proposed Fix' "$SOLUTION_FILE"; then
    QUALITY_SCORE=$((QUALITY_SCORE + 1))
    echo "[x] Has 'Proposed Fix' section"
fi

# Root cause identification (key metric for bug investigation)
if [ ${#GT_ROOT_CAUSE[@]} -gt 0 ]; then
    FOUND_ROOT=0
    for rc in "${GT_ROOT_CAUSE[@]}"; do
        rc_norm=$(_normalize_path "$rc")
        if grep -qi "$(basename "$rc")" "$SOLUTION_FILE" 2>/dev/null; then
            FOUND_ROOT=1
            break
        fi
    done
    if [ "$FOUND_ROOT" -eq 1 ]; then
        QUALITY_SCORE=$((QUALITY_SCORE + 3))
        echo "[x] Root cause file identified correctly"
    else
        echo "[ ] Root cause file not identified"
    fi
else
    QUALITY_SCORE=$((QUALITY_SCORE + 1))
fi

# Bug-specific keywords: check agent mentions key concepts
BUG_KEYWORDS=("BufferPool" "deallocate" "failBatch" "in-flight" "ByteBuffer" "ProducerBatch")
KW_FOUND=0
for kw in "${BUG_KEYWORDS[@]}"; do
    if grep -qi "$kw" "$SOLUTION_FILE" 2>/dev/null; then
        KW_FOUND=$((KW_FOUND + 1))
    fi
done
if [ "$KW_FOUND" -ge 4 ]; then
    QUALITY_SCORE=$((QUALITY_SCORE + 2))
    echo "[x] Key bug concepts identified ($KW_FOUND/${#BUG_KEYWORDS[@]} keywords)"
elif [ "$KW_FOUND" -ge 2 ]; then
    QUALITY_SCORE=$((QUALITY_SCORE + 1))
    echo "[~] Partial bug concept coverage ($KW_FOUND/${#BUG_KEYWORDS[@]} keywords)"
else
    echo "[ ] Missing key bug concepts ($KW_FOUND/${#BUG_KEYWORDS[@]} keywords)"
fi

TASK_QUALITY=$(awk "BEGIN {printf \"%.2f\", $QUALITY_SCORE / $QUALITY_MAX}")
echo "Task quality: $TASK_QUALITY ($QUALITY_SCORE / $QUALITY_MAX)"

# ── Composite score ──────────────────────────────────────────────────────
SCORE=$(composite_score "$TASK_QUALITY" "$IR_RECALL" "$IR_PRECISION" "$DEP_ACCURACY")

echo "$SCORE" > /logs/verifier/reward.txt
echo ""
echo "[x] Tests completed - Score: $SCORE (quality=$TASK_QUALITY recall=$IR_RECALL precision=$IR_PRECISION dep=$DEP_ACCURACY mrr=$ROOT_CAUSE_MRR)"
