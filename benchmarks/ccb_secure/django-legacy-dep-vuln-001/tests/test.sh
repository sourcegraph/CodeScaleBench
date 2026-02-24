#!/bin/bash
# Reward: checklist (0.0-1.0) — weighted correctness checks
# Verifies escape_with_encoding() in django/utils/html.py

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

echo "Running enterprise task 4 verification..."

SCORE_NUMERATOR=0

# Check 1 (0.25): escape_with_encoding function exists
if grep -q "def escape_with_encoding" django/utils/html.py 2>/dev/null; then
    echo "[x] escape_with_encoding function exists"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
else
    echo "[ ] escape_with_encoding function not found"
fi

# Check 2 (0.25): Correctly uses force_str with legacy parameters
LEGACY_FEATURES=0
if grep -qE "from django\.utils\.encoding import.*force_str|from django.utils.encoding import" django/utils/html.py 2>/dev/null; then
    LEGACY_FEATURES=$((LEGACY_FEATURES + 1))
fi
if grep -q "force_str" django/utils/html.py 2>/dev/null; then
    LEGACY_FEATURES=$((LEGACY_FEATURES + 1))
fi
if grep -q "strings_only" django/utils/html.py 2>/dev/null; then
    LEGACY_FEATURES=$((LEGACY_FEATURES + 1))
fi
if grep -qE "encoding|errors=" django/utils/html.py 2>/dev/null; then
    LEGACY_FEATURES=$((LEGACY_FEATURES + 1))
fi

case $LEGACY_FEATURES in
    4) echo "[x] Full legacy API integration (import, force_str, strings_only, encoding)"
       SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25)) ;;
    3) echo "[~] Most legacy API features ($LEGACY_FEATURES/4)"
       SCORE_NUMERATOR=$((SCORE_NUMERATOR + 18)) ;;
    2) echo "[~] Some legacy API features ($LEGACY_FEATURES/4)"
       SCORE_NUMERATOR=$((SCORE_NUMERATOR + 12)) ;;
    *) echo "[ ] Legacy API integration incomplete ($LEGACY_FEATURES/4)" ;;
esac

# Check 3 (0.25): Protected type handling + conditional_escape integration
ESCAPE_FEATURES=0
# Check for protected type awareness (is_protected_type or isinstance check or strings_only logic)
if grep -qE "(is_protected_type|protected_type|strings_only.*return|isinstance.*str)" django/utils/html.py 2>/dev/null; then
    # Look specifically in the diff for the new function's logic
    if git diff "$ORIGIN_REF..HEAD" -- django/utils/html.py 2>/dev/null | grep -qE "(is_protected_type|strings_only|isinstance)"; then
        ESCAPE_FEATURES=$((ESCAPE_FEATURES + 1))
    elif git diff -- django/utils/html.py 2>/dev/null | grep -qE "(is_protected_type|strings_only|isinstance)"; then
        ESCAPE_FEATURES=$((ESCAPE_FEATURES + 1))
    fi
fi
# Check for conditional_escape usage
if git diff "$ORIGIN_REF..HEAD" -- django/utils/html.py 2>/dev/null | grep -q "conditional_escape"; then
    ESCAPE_FEATURES=$((ESCAPE_FEATURES + 1))
elif git diff -- django/utils/html.py 2>/dev/null | grep -q "conditional_escape"; then
    ESCAPE_FEATURES=$((ESCAPE_FEATURES + 1))
fi

case $ESCAPE_FEATURES in
    2) echo "[x] Protected type handling + conditional_escape integration"
       SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25)) ;;
    1) echo "[~] Partial escaping logic ($ESCAPE_FEATURES/2)"
       SCORE_NUMERATOR=$((SCORE_NUMERATOR + 12)) ;;
    *) echo "[ ] Escaping logic not properly integrated" ;;
esac

# Check 4 (0.25): Python syntax valid + changes scoped to django/utils/html.py
SYNTAX_OK=false
SCOPE_OK=false

if python3 -c "import ast; ast.parse(open('django/utils/html.py').read())" 2>/logs/verifier/syntax_errors.txt; then
    echo "[x] Python syntax valid"
    SYNTAX_OK=true
else
    echo "[ ] Python syntax errors found"
fi

ALL_CHANGED=""
if [ -n "$ORIGIN_REF" ]; then
    ALL_CHANGED=$(git diff --name-only "$ORIGIN_REF..HEAD" 2>/dev/null)
fi
ALL_CHANGED="$ALL_CHANGED
$(git diff --name-only 2>/dev/null)
$(git diff --cached --name-only 2>/dev/null)
$(git ls-files --others --exclude-standard 2>/dev/null)"
ALL_CHANGED=$(echo "$ALL_CHANGED" | sort -u | grep -v '^$' || true)

OUTSIDE_SCOPE=0
if [ -n "$ALL_CHANGED" ]; then
    while IFS= read -r f; do
        case "$f" in
            django/utils/html.py) ;;
            *) OUTSIDE_SCOPE=1; echo "WARNING: change outside django/utils/html.py: $f" ;;
        esac
    done <<< "$ALL_CHANGED"
fi
if [ "$OUTSIDE_SCOPE" -eq 0 ]; then
    SCOPE_OK=true
    echo "[x] All changes within django/utils/html.py"
fi

if [ "$SYNTAX_OK" = true ] && [ "$SCOPE_OK" = true ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
elif [ "$SYNTAX_OK" = true ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 15))
    echo "[!] Changes outside django/utils/html.py"
elif [ "$SCOPE_OK" = true ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 10))
fi

SCORE=$(awk "BEGIN {printf \"%.2f\", $SCORE_NUMERATOR / 100}")
echo "$SCORE" > /logs/verifier/reward.txt
echo ""
echo "[x] Tests completed - Score: $SCORE"
