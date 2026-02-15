#!/bin/bash
# Reward: checklist (0.0-1.0) — weighted correctness checks
# Verifies ModelChoiceField prepare_value fix in django/forms/models.py

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

echo "Running enterprise task 1 verification..."

SCORE_NUMERATOR=0

# Check 1 (0.30): prepare_value uses to_field_name
if git diff "$ORIGIN_REF..HEAD" -- django/forms/models.py 2>/dev/null | grep -q "to_field_name"; then
    FOUND_FIX=true
elif git diff -- django/forms/models.py 2>/dev/null | grep -q "to_field_name"; then
    FOUND_FIX=true
else
    FOUND_FIX=false
fi

if [ "$FOUND_FIX" = true ]; then
    # Check that prepare_value method was modified (not just any to_field_name mention)
    if git diff "$ORIGIN_REF..HEAD" -- django/forms/models.py 2>/dev/null | grep -qE "(prepare_value|serializable_value)"; then
        echo "[x] prepare_value modified with to_field_name handling"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 30))
    elif git diff -- django/forms/models.py 2>/dev/null | grep -qE "(prepare_value|serializable_value)"; then
        echo "[x] prepare_value modified with to_field_name handling (unstaged)"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 30))
    else
        echo "[~] to_field_name referenced but prepare_value not clearly modified"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 15))
    fi
else
    echo "[ ] prepare_value not modified with to_field_name"
fi

# Check 2 (0.25): Python syntax valid
echo "Running syntax check..."
if python3 -c "import ast; ast.parse(open('django/forms/models.py').read())" 2>/logs/verifier/syntax_errors.txt; then
    echo "[x] Python syntax valid"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
else
    echo "[ ] Python syntax errors found"
fi

# Check 3 (0.25): Changes scoped to django/forms/ only
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
            django/forms/*) ;;
            *) OUTSIDE_SCOPE=1; echo "WARNING: change outside django/forms/: $f" ;;
        esac
    done <<< "$ALL_CHANGED"
fi
if [ "$OUTSIDE_SCOPE" -eq 0 ]; then
    echo "[x] All changes within django/forms/"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
else
    echo "[!] Changes outside django/forms/ — team boundary violation"
fi

# Check 4 (0.20): Fix handles model instance check correctly
# Look for the pattern: hasattr + to_field_name + serializable_value
if grep -qE "to_field_name.*serializable_value|serializable_value.*to_field_name" django/forms/models.py 2>/dev/null; then
    echo "[x] Fix uses serializable_value with to_field_name"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 20))
elif grep -qE "getattr.*to_field_name" django/forms/models.py 2>/dev/null; then
    echo "[~] Fix uses getattr with to_field_name (partial credit)"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 10))
else
    echo "[ ] Cannot verify correct value extraction pattern"
fi

SCORE=$(awk "BEGIN {printf \"%.2f\", $SCORE_NUMERATOR / 100}")
echo "$SCORE" > /logs/verifier/reward.txt
echo ""
echo "[x] Tests completed - Score: $SCORE"
