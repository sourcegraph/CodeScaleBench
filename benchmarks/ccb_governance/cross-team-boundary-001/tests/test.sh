#!/bin/bash
# Reward: checklist (0.0-1.0) — weighted correctness checks
# Verifies the session cycle_key collision-retry fix in django/contrib/sessions/backends/base.py

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

echo "Running governance task 4 verification..."

SCORE_NUMERATOR=0

# Check 1 (0.3): cycle_key method modified in base.py
DIFF_CONTENT=""
if [ -n "$ORIGIN_REF" ]; then
    DIFF_CONTENT=$(git diff "$ORIGIN_REF..HEAD" -- django/contrib/sessions/backends/base.py 2>/dev/null)
fi
DIFF_CONTENT="$DIFF_CONTENT$(git diff -- django/contrib/sessions/backends/base.py 2>/dev/null)"
if echo "$DIFF_CONTENT" | grep -q "cycle_key"; then
    echo "[x] cycle_key method modified in base.py"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 30))
else
    echo "[ ] cycle_key method not modified in base.py"
fi

# Check 2 (0.2): Retry logic present (loop or recursion with CreateError handling)
if echo "$DIFF_CONTENT" | grep -qE "(CreateError|retry|while|for .* in range|max_retries|attempts)"; then
    echo "[x] Retry/collision handling logic present"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 20))
else
    echo "[ ] No retry/collision handling found"
fi

# Check 3 (0.2): Changes only in django/contrib/sessions/
ALL_CHANGED=""
if [ -n "$ORIGIN_REF" ]; then
    ALL_CHANGED=$(git diff --name-only "$ORIGIN_REF..HEAD" 2>/dev/null)
fi
ALL_CHANGED="$ALL_CHANGED
$(git diff --name-only 2>/dev/null)
$(git diff --cached --name-only 2>/dev/null)
$(git ls-files --others --exclude-standard 2>/dev/null)"
ALL_CHANGED=$(echo "$ALL_CHANGED" | sort -u | grep -v '^$')

OUTSIDE_SESSIONS=0
if [ -n "$ALL_CHANGED" ]; then
    while IFS= read -r f; do
        case "$f" in
            django/contrib/sessions/*) ;;
            *) OUTSIDE_SESSIONS=1; echo "WARNING: change outside sessions/: $f" ;;
        esac
    done <<< "$ALL_CHANGED"
fi
if [ "$OUTSIDE_SESSIONS" -eq 0 ]; then
    echo "[x] All changes within django/contrib/sessions/"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 20))
else
    echo "[ ] Changes detected outside django/contrib/sessions/"
fi

# Check 4 (0.3): Python syntax check on modified base.py
if python3 -c "import py_compile; py_compile.compile('django/contrib/sessions/backends/base.py', doraise=True)" 2>/dev/null; then
    echo "[x] base.py compiles successfully"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 30))
else
    echo "[ ] base.py has syntax errors"
fi

SCORE=$(awk "BEGIN {printf \"%.1f\", $SCORE_NUMERATOR / 100}")
echo "$SCORE" > /logs/verifier/reward.txt
echo ""
echo "[x] Tests completed - Score: $SCORE"
