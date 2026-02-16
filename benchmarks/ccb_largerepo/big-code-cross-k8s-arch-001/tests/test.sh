#!/bin/bash
# Reward: ir_checklist (0.0-1.0) — IR metrics + keyword overlap for cross-repo architectural analysis
# Composite: 0.4 * task_quality + 0.3 * file_recall + 0.2 * file_precision + 0.1 * dep_accuracy

set -e
cd /workspace
mkdir -p /logs/verifier

# Fix git safe.directory
git config --global --add safe.directory /workspace 2>/dev/null || true

# ── Source shared verifier library ────────────────────────────────────────
source /workspace/tests/verifier_lib.sh

# ── Change detection guard ────────────────────────────────────────────────
SOLUTION_FILE="/logs/agent/solution.md"
if [ ! -f "$SOLUTION_FILE" ]; then
    echo "No solution.md found — agent did not produce output"
    echo "0.0" > /logs/verifier/reward.txt
    echo "[ ] Tests completed - Score: 0.0 (no output)"
    exit 0
fi

SOLUTION_SIZE=$(wc -c < "$SOLUTION_FILE" 2>/dev/null || echo 0)
if [ "$SOLUTION_SIZE" -lt 200 ]; then
    echo "Solution.md too short ($SOLUTION_SIZE bytes) — likely incomplete"
    echo "0.0" > /logs/verifier/reward.txt
    echo "[ ] Tests completed - Score: 0.0 (insufficient output)"
    exit 0
fi

echo "Solution file found ($SOLUTION_SIZE bytes)"

# ── IR metrics pipeline ──────────────────────────────────────────────────
run_ir_pipeline "$SOLUTION_FILE" "/workspace/tests/ground_truth.json" "/logs/verifier/ir_metrics.json"

# ── Task quality scoring (keyword-based) ─────────────────────────────────
QUALITY_SCORE=0
QUALITY_MAX=10

# Check for required sections
if grep -qiE '^##\s+(Files Examined|Files Analyzed)' "$SOLUTION_FILE"; then
    QUALITY_SCORE=$((QUALITY_SCORE + 2))
    echo "[x] Has 'Files Examined' section"
else
    echo "[ ] Missing 'Files Examined' section"
fi

if grep -qiE '^##\s+(Dependency Chain|Component Relationships)' "$SOLUTION_FILE"; then
    QUALITY_SCORE=$((QUALITY_SCORE + 2))
    echo "[x] Has 'Dependency Chain' section"
else
    echo "[ ] Missing 'Dependency Chain' section"
fi

if grep -qiE '^##\s+(Analysis|Summary|Architecture)' "$SOLUTION_FILE"; then
    QUALITY_SCORE=$((QUALITY_SCORE + 2))
    echo "[x] Has 'Analysis' section"
else
    echo "[ ] Missing 'Analysis' section"
fi

# CRD cross-repo-specific keywords
ARCH_KEYWORDS="CustomResourceDefinition|GroupVersionKind|GroupVersionResource|Scheme|Unstructured|apiextensions|DynamicClient|SharedIndexInformer|etcd|validation|customresource_handler|TypeMeta|ObjectMeta|register|Lister|Informer"
KEYWORD_HITS=$(grep -ciE "$ARCH_KEYWORDS" "$SOLUTION_FILE" 2>/dev/null || echo 0)
if [ "$KEYWORD_HITS" -ge 5 ]; then
    QUALITY_SCORE=$((QUALITY_SCORE + 2))
    echo "[x] Architecture keywords found ($KEYWORD_HITS hits)"
elif [ "$KEYWORD_HITS" -ge 2 ]; then
    QUALITY_SCORE=$((QUALITY_SCORE + 1))
    echo "[~] Some architecture keywords found ($KEYWORD_HITS hits)"
else
    echo "[ ] Few architecture keywords ($KEYWORD_HITS hits)"
fi

# Check for sufficient depth (word count proxy)
WORD_COUNT=$(wc -w < "$SOLUTION_FILE" 2>/dev/null || echo 0)
if [ "$WORD_COUNT" -ge 500 ]; then
    QUALITY_SCORE=$((QUALITY_SCORE + 2))
    echo "[x] Sufficient analysis depth ($WORD_COUNT words)"
elif [ "$WORD_COUNT" -ge 200 ]; then
    QUALITY_SCORE=$((QUALITY_SCORE + 1))
    echo "[~] Moderate analysis depth ($WORD_COUNT words)"
else
    echo "[ ] Shallow analysis ($WORD_COUNT words)"
fi

TASK_QUALITY=$(awk "BEGIN {printf \"%.2f\", $QUALITY_SCORE / $QUALITY_MAX}")
echo "Task quality: $TASK_QUALITY ($QUALITY_SCORE / $QUALITY_MAX)"

# ── Composite score ──────────────────────────────────────────────────────
SCORE=$(composite_score "$TASK_QUALITY" "$IR_RECALL" "$IR_PRECISION" "$DEP_ACCURACY")

echo "$SCORE" > /logs/verifier/reward.txt
echo ""
echo "[x] Tests completed - Score: $SCORE (quality=$TASK_QUALITY recall=$IR_RECALL precision=$IR_PRECISION dep=$DEP_ACCURACY)"
