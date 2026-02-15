#!/bin/bash
# Reward: ir_checklist (0.0-1.0) — IR metrics + completeness check for cross-file refactoring
# Composite: 0.4 * task_quality + 0.3 * file_recall + 0.2 * file_precision + 0.1 * dep_accuracy

set -e
cd /workspace
mkdir -p /logs/verifier

git config --global --add safe.directory /workspace 2>/dev/null || true

# ── Source shared verifier library ────────────────────────────────────────
source /workspace/tests/verifier_lib.sh

# ── Change detection guard ────────────────────────────────────────────────
# Refactoring tasks require actual code changes OR a detailed solution.md
SOLUTION_FILE="/logs/agent/solution.md"
UNSTAGED_COUNT=$(git diff --stat 2>/dev/null | wc -l)
STAGED_COUNT=$(git diff --cached --stat 2>/dev/null | wc -l)
UNTRACKED_COUNT=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l)

ORIGIN_REF=""
for ref in origin/master origin/main origin/HEAD; do
    if git rev-parse "$ref" >/dev/null 2>&1; then
        ORIGIN_REF="$ref"; break
    fi
done
COMMIT_COUNT=0
if [ -n "$ORIGIN_REF" ]; then
    COMMIT_COUNT=$(git log --oneline "$ORIGIN_REF..HEAD" 2>/dev/null | wc -l)
fi

HAS_CHANGES=0
if [ "$UNSTAGED_COUNT" -gt 0 ] || [ "$STAGED_COUNT" -gt 0 ] || [ "$UNTRACKED_COUNT" -gt 0 ] || [ "$COMMIT_COUNT" -gt 0 ]; then
    HAS_CHANGES=1
fi
HAS_SOLUTION=0
if [ -f "$SOLUTION_FILE" ] && [ "$(wc -c < "$SOLUTION_FILE" 2>/dev/null || echo 0)" -ge 200 ]; then
    HAS_SOLUTION=1
fi

if [ "$HAS_CHANGES" -eq 0 ] && [ "$HAS_SOLUTION" -eq 0 ]; then
    echo "No code changes and no solution.md — agent did not execute"
    echo "0.0" > /logs/verifier/reward.txt
    echo "[ ] Tests completed - Score: 0.0 (no output)"
    exit 0
fi

# ── IR metrics pipeline ──────────────────────────────────────────────────
if [ "$HAS_SOLUTION" -eq 1 ]; then
    run_ir_pipeline "$SOLUTION_FILE" "/workspace/tests/ground_truth.json" "/logs/verifier/ir_metrics.json"
else
    # Extract files from git diff if no solution.md
    load_ground_truth "/workspace/tests/ground_truth.json"
    AGENT_FILES=()
    while IFS= read -r f; do
        [ -n "$f" ] && AGENT_FILES+=("$f")
    done < <(git diff --name-only 2>/dev/null; git diff --cached --name-only 2>/dev/null)
    if [ -n "$ORIGIN_REF" ]; then
        while IFS= read -r f; do
            [ -n "$f" ] && AGENT_FILES+=("$f")
        done < <(git diff --name-only "$ORIGIN_REF..HEAD" 2>/dev/null)
    fi
    compute_ir_metrics "/workspace/tests/ground_truth.json"
    compute_dep_accuracy
    write_ir_metrics "/logs/verifier/ir_metrics.json"
fi

# ── Task quality scoring ─────────────────────────────────────────────────
QUALITY_SCORE=0
QUALITY_MAX=10

# Check for code changes (refactoring should produce actual changes)
if [ "$HAS_CHANGES" -eq 1 ]; then
    QUALITY_SCORE=$((QUALITY_SCORE + 3))
    echo "[x] Code changes detected"
else
    echo "[ ] No code changes (solution.md only)"
fi

# Check for structured output
if [ "$HAS_SOLUTION" -eq 1 ]; then
    if grep -qiE '^##\s+Code Changes' "$SOLUTION_FILE"; then
        QUALITY_SCORE=$((QUALITY_SCORE + 2))
        echo "[x] Has 'Code Changes' section"
    else
        echo "[ ] Missing 'Code Changes' section"
    fi

    # Check completeness: no stale references mentioned
    if grep -qiE '(stale|remaining|TODO|FIXME|not.updated)' "$SOLUTION_FILE"; then
        echo "[~] Possible incomplete refactoring noted"
    else
        QUALITY_SCORE=$((QUALITY_SCORE + 2))
        echo "[x] No stale reference warnings"
    fi

    if grep -qiE '^##\s+(Analysis|Verification)' "$SOLUTION_FILE"; then
        QUALITY_SCORE=$((QUALITY_SCORE + 1))
        echo "[x] Has 'Analysis' section"
    fi
fi

# Check compilation (Go)
COMPILE_CMD="go build ./pkg/scheduler/..."
if eval "$COMPILE_CMD" 2>/logs/verifier/build_errors.txt; then
    QUALITY_SCORE=$((QUALITY_SCORE + 2))
    echo "[x] Compilation passed"
else
    echo "[ ] Compilation failed"
fi

TASK_QUALITY=$(awk "BEGIN {printf \"%.2f\", $QUALITY_SCORE / $QUALITY_MAX}")
echo "Task quality: $TASK_QUALITY ($QUALITY_SCORE / $QUALITY_MAX)"

# ── Composite score ──────────────────────────────────────────────────────
SCORE=$(composite_score "$TASK_QUALITY" "$IR_RECALL" "$IR_PRECISION" "$DEP_ACCURACY")

echo "$SCORE" > /logs/verifier/reward.txt
echo ""
echo "[x] Tests completed - Score: $SCORE (quality=$TASK_QUALITY recall=$IR_RECALL precision=$IR_PRECISION dep=$DEP_ACCURACY)"
