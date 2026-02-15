#!/bin/bash
# Reward: checklist (0.0-1.0) — weighted correctness checks
# Verifies evaluation duration tracking in flipt internal/server/evaluation/

set -e

cd /workspace

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

echo "Running enterprise task 3 verification..."

SCORE_NUMERATOR=0

# Check 1 (0.25): duration.go file exists with DurationTracker struct
if [ -f "internal/server/evaluation/duration.go" ]; then
    if grep -q "DurationTracker" internal/server/evaluation/duration.go; then
        echo "[x] duration.go exists with DurationTracker struct"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
    else
        echo "[~] duration.go exists but missing DurationTracker struct"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 10))
    fi
else
    echo "[ ] duration.go not found"
fi

# Check 2 (0.20): Thread safety (sync.RWMutex or sync.Mutex)
if [ -f "internal/server/evaluation/duration.go" ]; then
    if grep -qE "sync\.(RW)?Mutex" internal/server/evaluation/duration.go; then
        echo "[x] Thread-safe implementation found"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 20))
    else
        echo "[ ] No mutex found in duration.go"
    fi
else
    echo "[ ] Cannot check thread safety (no duration.go)"
fi

# Check 3 (0.20): Server struct integration (duration tracker added)
SERVER_MODIFIED=false
if git diff "$ORIGIN_REF..HEAD" -- internal/server/evaluation/server.go 2>/dev/null | grep -qi "duration"; then
    SERVER_MODIFIED=true
elif git diff -- internal/server/evaluation/server.go 2>/dev/null | grep -qi "duration"; then
    SERVER_MODIFIED=true
fi

if [ "$SERVER_MODIFIED" = true ]; then
    echo "[x] Server struct modified with duration tracker"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 20))
else
    echo "[ ] Server struct not modified with duration tracking"
fi

# Check 4 (0.10): Evaluation methods instrumented (time.Now/time.Since in evaluation.go)
EVAL_MODIFIED=false
if git diff "$ORIGIN_REF..HEAD" -- internal/server/evaluation/evaluation.go 2>/dev/null | grep -qiE "time\.(Now|Since)|duration"; then
    EVAL_MODIFIED=true
elif git diff -- internal/server/evaluation/evaluation.go 2>/dev/null | grep -qiE "time\.(Now|Since)|duration"; then
    EVAL_MODIFIED=true
fi

if [ "$EVAL_MODIFIED" = true ]; then
    echo "[x] Evaluation methods instrumented with duration recording"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 10))
else
    echo "[ ] Evaluation methods not instrumented"
fi

# Check 5 (0.25): Go compilation succeeds
echo "Running Go compilation check..."
if go build ./internal/server/evaluation/... 2>/logs/verifier/build_errors.txt; then
    echo "[x] Go compilation passed"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
else
    echo "[ ] Go compilation failed"
    head -20 /logs/verifier/build_errors.txt 2>/dev/null
fi

# Scope check: all changes within evaluation package
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
    echo "[!] Changes outside evaluation/ — team boundary concern"
fi

SCORE=$(awk "BEGIN {printf \"%.2f\", $SCORE_NUMERATOR / 100}")
echo "$SCORE" > /logs/verifier/reward.txt
echo ""
echo "[x] Tests completed - Score: $SCORE"
