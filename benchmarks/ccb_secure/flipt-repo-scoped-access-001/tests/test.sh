#!/bin/bash
# Reward: checklist (0.0-1.0) — weighted correctness checks
# Verifies evaluation metrics feature in flipt internal/server/evaluation/

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

# Guard: check for code changes
UNSTAGED_COUNT=$(git diff --stat 2>/dev/null | wc -l)
STAGED_COUNT=$(git diff --cached --stat 2>/dev/null | wc -l)
UNTRACKED_COUNT=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l)
COMMIT_COUNT=0
ORIGIN_REF=""
for ref in origin/master origin/main origin/HEAD; do
    if git rev-parse "$ref" >/dev/null 2>&1; then
        ORIGIN_REF="$ref"
        break
    fi
done
if [ -n "$ORIGIN_REF" ]; then
    COMMIT_COUNT=$(git log --oneline "$ORIGIN_REF..HEAD" 2>/dev/null | wc -l)
fi
echo "Change detection: unstaged=$UNSTAGED_COUNT staged=$STAGED_COUNT untracked=$UNTRACKED_COUNT commits=$COMMIT_COUNT"
if [ "$UNSTAGED_COUNT" -eq 0 ] && [ "$STAGED_COUNT" -eq 0 ] && [ "$UNTRACKED_COUNT" -eq 0 ] && [ "$COMMIT_COUNT" -eq 0 ]; then
    echo "No code changes detected"
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

echo "Running governance task 2 verification..."

SCORE_NUMERATOR=0

# Check 1 (0.25): metrics.go file exists with EvaluationMetrics struct
if [ -f "internal/server/evaluation/metrics.go" ]; then
    if grep -q "EvaluationMetrics" internal/server/evaluation/metrics.go; then
        echo "[x] metrics.go exists with EvaluationMetrics struct"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
    else
        echo "[~] metrics.go exists but missing EvaluationMetrics struct"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 10))
    fi
else
    echo "[ ] metrics.go not found"
fi

# Check 2 (0.25): Concurrent safety (sync.Mutex or sync.RWMutex)
if [ -f "internal/server/evaluation/metrics.go" ]; then
    if grep -qE "sync\.(RW)?Mutex" internal/server/evaluation/metrics.go; then
        echo "[x] Concurrent-safe implementation found"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
    else
        echo "[ ] No mutex found in metrics.go"
    fi
else
    echo "[ ] Cannot check concurrency (no metrics.go)"
fi

# Check 3 (0.25): Server struct integration (metrics field added to server.go)
if git diff --unified=0 "$ORIGIN_REF..HEAD" -- internal/server/evaluation/server.go 2>/dev/null | grep -qi "metrics"; then
    echo "[x] Server struct modified with metrics integration"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
elif git diff --unified=0 -- internal/server/evaluation/server.go 2>/dev/null | grep -qi "metrics"; then
    echo "[x] Server struct modified with metrics integration (unstaged)"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
else
    echo "[ ] Server struct not modified with metrics"
fi

# Check 4 (0.25): Go compilation succeeds
echo "Running Go compilation check..."
if go build ./internal/server/evaluation/... 2>/logs/verifier/build_errors.txt; then
    echo "[x] Go compilation passed"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
else
    echo "[ ] Go compilation failed"
fi

# Bonus penalty: check changes are scoped to evaluation package
ALL_CHANGED=""
if [ -n "$ORIGIN_REF" ]; then
    ALL_CHANGED=$(git diff --name-only "$ORIGIN_REF..HEAD" 2>/dev/null)
fi
ALL_CHANGED="$ALL_CHANGED
$(git diff --name-only 2>/dev/null)
$(git diff --cached --name-only 2>/dev/null)
$(git ls-files --others --exclude-standard 2>/dev/null)"
ALL_CHANGED=$(echo "$ALL_CHANGED" | sort -u | grep -v '^$')

OUTSIDE_SCOPE=0
if [ -n "$ALL_CHANGED" ]; then
    while IFS= read -r f; do
        case "$f" in
            internal/server/evaluation/*) ;;
            *) OUTSIDE_SCOPE=1; echo "WARNING: change outside evaluation/: $f" ;;
        esac
    done <<< "$ALL_CHANGED"
fi
if [ "$OUTSIDE_SCOPE" -eq 0 ]; then
    echo "[x] All changes within internal/server/evaluation/"
else
    echo "[!] Changes outside evaluation/ — governance concern"
fi

SCORE=$(awk "BEGIN {printf \"%.2f\", $SCORE_NUMERATOR / 100}")
echo "$SCORE" > /logs/verifier/reward.txt
echo ""
echo "[x] Tests completed - Score: $SCORE"
