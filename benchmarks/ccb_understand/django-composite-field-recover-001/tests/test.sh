#!/bin/bash
set -e

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

cd /workspace
mkdir -p /logs/verifier
git config --global --add safe.directory /workspace 2>/dev/null || true

UNSTAGED=$(git diff --stat 2>/dev/null | wc -l)
STAGED=$(git diff --cached --stat 2>/dev/null | wc -l)
UNTRACKED=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l)
COMMITS=0
for ref in origin/master origin/main origin/HEAD; do
    if git rev-parse "$ref" >/dev/null 2>&1; then
        COMMITS=$(git log --oneline "$ref..HEAD" 2>/dev/null | wc -l)
        break
    fi
done
if [ "$UNSTAGED" -eq 0 ] && [ "$STAGED" -eq 0 ] && [ "$UNTRACKED" -eq 0 ] && [ "$COMMITS" -eq 0 ]; then
    echo "No code changes detected"
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

SCORE=0

# Check 1 (25): CompositFieldValidator class exists in django/forms/
if grep -rq "class CompositFieldValidator" django/forms/ 2>/dev/null; then
    echo "[x] CompositFieldValidator class found in django/forms/"
    SCORE=$((SCORE + 25))
else
    echo "[ ] CompositFieldValidator class not found in django/forms/"
fi

# Check 2 (25): Integrates with validation pipeline (references clean, validate, or ValidationError)
INTEGRATION=0
if grep -rq "ValidationError" django/forms/ 2>/dev/null; then
    INTEGRATION=$((INTEGRATION + 1))
fi
if grep -rqE "(clean|validate|_clean_fields|_clean_form)" django/forms/ 2>/dev/null; then
    INTEGRATION=$((INTEGRATION + 1))
fi
if grep -rqE "(field_names|fields)" django/forms/ 2>/dev/null && grep -rq "CompositFieldValidator" django/forms/ 2>/dev/null; then
    INTEGRATION=$((INTEGRATION + 1))
fi
case $INTEGRATION in
    3) echo "[x] Full validation pipeline integration"; SCORE=$((SCORE + 25)) ;;
    2) echo "[~] Partial validation integration ($INTEGRATION/3)"; SCORE=$((SCORE + 15)) ;;
    1) echo "[~] Minimal validation integration ($INTEGRATION/3)"; SCORE=$((SCORE + 10)) ;;
    *) echo "[ ] No validation pipeline integration" ;;
esac

# Check 3 (25): Uses Django's existing patterns (imports from django.core.exceptions, handles field refs)
PATTERNS=0
if grep -rqE "from django\.(core\.exceptions|forms)" django/forms/ 2>/dev/null && grep -rq "CompositFieldValidator" django/forms/ 2>/dev/null; then
    PATTERNS=$((PATTERNS + 1))
fi
if grep -rqE "(def __init__|def __call__|def validate)" django/forms/ 2>/dev/null && grep -rq "CompositFieldValidator" django/forms/ 2>/dev/null; then
    PATTERNS=$((PATTERNS + 1))
fi
if grep -rqE "(KeyError|AttributeError|field.*not.*found|missing.*field)" django/forms/ 2>/dev/null; then
    PATTERNS=$((PATTERNS + 1))
fi
case $PATTERNS in
    3) echo "[x] Follows Django validation patterns"; SCORE=$((SCORE + 25)) ;;
    2) echo "[~] Partially follows patterns ($PATTERNS/3)"; SCORE=$((SCORE + 15)) ;;
    1) echo "[~] Minimal pattern adherence ($PATTERNS/3)"; SCORE=$((SCORE + 10)) ;;
    *) echo "[ ] Does not follow Django patterns" ;;
esac

# Check 4 (25): Syntax valid + scoped
SYNTAX_OK=true
SCOPE_OK=true
for f in $(git diff --name-only 2>/dev/null; git diff --cached --name-only 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null); do
    case "$f" in
        django/forms/*) ;;
        *) SCOPE_OK=false; echo "WARNING: change outside scope: $f" ;;
    esac
done
for pyf in $(git diff --name-only 2>/dev/null; git diff --cached --name-only 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null); do
    case "$pyf" in
        *.py)
            if ! python3 -c "import ast; ast.parse(open('$pyf').read())" 2>/dev/null; then
                SYNTAX_OK=false
                echo "[ ] Syntax error in $pyf"
            fi ;;
    esac
done
if [ "$SYNTAX_OK" = true ] && [ "$SCOPE_OK" = true ]; then
    echo "[x] Syntax valid, changes scoped"
    SCORE=$((SCORE + 25))
elif [ "$SYNTAX_OK" = true ]; then
    echo "[~] Syntax valid but out of scope"
    SCORE=$((SCORE + 15))
fi

REWARD=$(awk "BEGIN {printf \"%.2f\", $SCORE / 100}")
echo "$REWARD" > /logs/verifier/reward.txt
echo "Score: $REWARD"
