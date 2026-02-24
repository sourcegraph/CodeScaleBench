#!/bin/bash
# Reward: checklist (0.0-1.0) — weighted correctness checks
# Verifies the RelatedFieldListFilter.has_output() fix in django/contrib/admin/filters.py

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

echo "Running governance task 1 verification..."

SCORE_NUMERATOR=0

# Check 1 (0.3): has_output method modified in filters.py
if git diff --unified=0 $ORIGIN_REF..HEAD -- django/contrib/admin/filters.py 2>/dev/null | grep -q "has_output"; then
    echo "[x] has_output method modified in filters.py"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 3))
elif git diff --unified=0 -- django/contrib/admin/filters.py 2>/dev/null | grep -q "has_output"; then
    echo "[x] has_output method modified in filters.py (unstaged)"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 3))
else
    echo "[ ] has_output method not modified in filters.py"
fi

# Check 2 (0.2): Changes only in django/contrib/admin/
ALL_CHANGED=""
if [ -n "$ORIGIN_REF" ]; then
    ALL_CHANGED=$(git diff --name-only "$ORIGIN_REF..HEAD" 2>/dev/null)
fi
ALL_CHANGED="$ALL_CHANGED
$(git diff --name-only 2>/dev/null)
$(git diff --cached --name-only 2>/dev/null)"
ALL_CHANGED=$(echo "$ALL_CHANGED" | sort -u | grep -v '^$' || true)

OUTSIDE_ADMIN=0
if [ -n "$ALL_CHANGED" ]; then
    while IFS= read -r f; do
        case "$f" in
            django/contrib/admin/*) ;;
            *) OUTSIDE_ADMIN=1; echo "WARNING: change outside admin/: $f" ;;
        esac
    done <<< "$ALL_CHANGED"
fi
if [ "$OUTSIDE_ADMIN" -eq 0 ]; then
    echo "[x] All changes within django/contrib/admin/"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 2))
else
    echo "[ ] Changes detected outside django/contrib/admin/"
fi

# Check 3 (0.2): lookup_choices referenced in the change
DIFF_CONTENT=""
if [ -n "$ORIGIN_REF" ]; then
    DIFF_CONTENT=$(git diff "$ORIGIN_REF..HEAD" -- django/contrib/admin/filters.py 2>/dev/null)
fi
DIFF_CONTENT="$DIFF_CONTENT$(git diff -- django/contrib/admin/filters.py 2>/dev/null)"
if echo "$DIFF_CONTENT" | grep -q "lookup_choices"; then
    echo "[x] Fix references lookup_choices"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 2))
else
    echo "[ ] Fix does not reference lookup_choices"
fi

# Check 4 (0.3): Python syntax check on modified filters.py
if python3 -c "import py_compile; py_compile.compile('django/contrib/admin/filters.py', doraise=True)" 2>/dev/null; then
    echo "[x] filters.py compiles successfully"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 3))
else
    echo "[ ] filters.py has syntax errors"
fi

SCORE=$(awk "BEGIN {printf \"%.1f\", $SCORE_NUMERATOR / 10}")
echo "$SCORE" > /logs/verifier/reward.txt
echo ""
echo "[x] Tests completed - Score: $SCORE"
