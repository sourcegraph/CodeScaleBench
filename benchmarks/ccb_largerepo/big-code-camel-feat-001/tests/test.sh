#!/bin/bash
# Reward: ir_checklist (0.0-1.0) — compilation + IR metrics + keyword scoring
# Composite: 0.4 * task_quality + 0.3 * file_recall + 0.2 * file_precision + 0.1 * dep_accuracy

set -e
cd /workspace
mkdir -p /logs/verifier

git config --global --add safe.directory /workspace 2>/dev/null || true

# ── Source shared verifier library ────────────────────────────────────────
source /workspace/tests/verifier_lib.sh

# ── Change detection guard ────────────────────────────────────────────────
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
elif git rev-parse FETCH_HEAD >/dev/null 2>&1; then
    COMMIT_COUNT=$(git log --oneline FETCH_HEAD..HEAD 2>/dev/null | wc -l)
else
    TOTAL_COMMITS=$(git log --oneline 2>/dev/null | wc -l)
    [ "$TOTAL_COMMITS" -gt 1 ] && COMMIT_COUNT=$((TOTAL_COMMITS - 1))
fi

echo "Change detection: unstaged=$UNSTAGED_COUNT staged=$STAGED_COUNT untracked=$UNTRACKED_COUNT commits=$COMMIT_COUNT"

SOLUTION_FILE="/logs/agent/solution.md"
HAS_CHANGES=0
if [ "$UNSTAGED_COUNT" -gt 0 ] || [ "$STAGED_COUNT" -gt 0 ] || [ "$UNTRACKED_COUNT" -gt 0 ] || [ "$COMMIT_COUNT" -gt 0 ]; then
    HAS_CHANGES=1
fi
HAS_SOLUTION=0
if [ -f "$SOLUTION_FILE" ] && [ "$(wc -c < "$SOLUTION_FILE" 2>/dev/null || echo 0)" -ge 100 ]; then
    HAS_SOLUTION=1
fi

if [ "$HAS_CHANGES" -eq 0 ] && [ "$HAS_SOLUTION" -eq 0 ]; then
    echo "No code changes and no solution.md — agent did not execute"
    echo "0.0" > /logs/verifier/reward.txt
    echo "[ ] Tests completed - Score: 0.0 (no output)"
    exit 0
fi

# ── IR metrics ───────────────────────────────────────────────────────────
if [ "$HAS_SOLUTION" -eq 1 ]; then
    run_ir_pipeline "$SOLUTION_FILE" "/workspace/tests/ground_truth.json" "/logs/verifier/ir_metrics.json"
else
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

# ── Task quality: compilation + keyword scoring ──────────────────────────
QUALITY_SCORE=0
QUALITY_MAX=10

# Compilation check — build the new camel-fix module if it exists
COMPILE_CMD=""
if [ -d "components/camel-fix" ] && [ -f "components/camel-fix/pom.xml" ]; then
    COMPILE_CMD="mvn compile -pl components/camel-fix -q"
fi
if [ -n "$COMPILE_CMD" ]; then
    echo "Running compilation check..."
    if eval "$COMPILE_CMD" 2>/logs/verifier/build_errors.txt; then
        QUALITY_SCORE=$((QUALITY_SCORE + 4))
        echo "[x] Compilation passed"
    else
        echo "[ ] Compilation failed — capping task quality"
        QUALITY_MAX=20
    fi
else
    QUALITY_SCORE=$((QUALITY_SCORE + 2))
    echo "[~] No camel-fix module found, partial compilation credit"
fi

# Keyword scoring — FIX component-specific terms
FEATURE_KEYWORDS="FixComponent|FixEndpoint|FixConsumer|FixProducer|FixConfiguration|DefaultComponent|@UriEndpoint|@UriParam|@Component|createEndpoint|FIX protocol"
if [ -n "$FEATURE_KEYWORDS" ]; then
    KEYWORD_HITS=$(grep -rciE "$FEATURE_KEYWORDS" . --include="*.java" 2>/dev/null | awk -F: '{s+=$2} END {print s+0}')
    if [ "$KEYWORD_HITS" -ge 3 ]; then
        QUALITY_SCORE=$((QUALITY_SCORE + 3))
        echo "[x] Feature keywords found ($KEYWORD_HITS hits)"
    elif [ "$KEYWORD_HITS" -ge 1 ]; then
        QUALITY_SCORE=$((QUALITY_SCORE + 1))
        echo "[~] Some feature keywords ($KEYWORD_HITS hits)"
    else
        echo "[ ] Feature keywords not found"
    fi
else
    QUALITY_SCORE=$((QUALITY_SCORE + 1))
fi

# File change breadth
CHANGED_FILES=""
if [ -n "$ORIGIN_REF" ]; then
    CHANGED_FILES=$(git diff --name-only "$ORIGIN_REF..HEAD" 2>/dev/null)
fi
CHANGED_FILES="$CHANGED_FILES
$(git diff --name-only 2>/dev/null)
$(git diff --cached --name-only 2>/dev/null)"
CHANGE_COUNT=$(echo "$CHANGED_FILES" | grep -c '.' 2>/dev/null || echo 0)

if [ "$CHANGE_COUNT" -ge 3 ]; then
    QUALITY_SCORE=$((QUALITY_SCORE + 2))
    echo "[x] Multi-file changes ($CHANGE_COUNT files)"
elif [ "$CHANGE_COUNT" -ge 1 ]; then
    QUALITY_SCORE=$((QUALITY_SCORE + 1))
    echo "[~] Limited changes ($CHANGE_COUNT files)"
fi

# Test additions
if echo "$CHANGED_FILES" | grep -qiE '(Test\.java|_test\.|test_|_spec\.)'; then
    QUALITY_SCORE=$((QUALITY_SCORE + 1))
    echo "[x] Test files modified"
fi

TASK_QUALITY=$(awk "BEGIN {printf \"%.2f\", $QUALITY_SCORE / $QUALITY_MAX}")
echo "Task quality: $TASK_QUALITY ($QUALITY_SCORE / $QUALITY_MAX)"

# ── Composite score ──────────────────────────────────────────────────────
SCORE=$(composite_score "$TASK_QUALITY" "$IR_RECALL" "$IR_PRECISION" "$DEP_ACCURACY")

echo "$SCORE" > /logs/verifier/reward.txt
echo ""
echo "[x] Tests completed - Score: $SCORE (quality=$TASK_QUALITY recall=$IR_RECALL precision=$IR_PRECISION dep=$DEP_ACCURACY)"
