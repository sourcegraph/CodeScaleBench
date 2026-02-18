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
        COMMITS=$((COMMITS - 1))
        [ "$COMMITS" -lt 0 ] && COMMITS=0
        break
    fi
done
if [ "$UNSTAGED" -eq 0 ] && [ "$STAGED" -eq 0 ] && [ "$UNTRACKED" -eq 0 ] && [ "$COMMITS" -eq 0 ]; then
    echo "No code changes detected"
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

DIFF=$(git diff HEAD~1..HEAD -- django/template/ 2>/dev/null || git diff -- django/template/ 2>/dev/null)
ALL_CHANGED=$(git diff --name-only 2>/dev/null; git diff --cached --name-only 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null)

SCORE=0

# Check 1 (30): Changes in template block resolution code
if echo "$DIFF" | grep -qE "(block|Block|BlockNode|ExtendsNode|render_block|block_context)"; then
    echo "[x] Block-related changes found in django/template/"
    SCORE=$((SCORE + 30))
elif [ -n "$DIFF" ]; then
    echo "[~] Changes in django/template/ but not in block resolution"
    SCORE=$((SCORE + 10))
else
    echo "[ ] No changes in django/template/"
fi

# Check 2 (25): Fix targets nested/multi-level inheritance
MULTI_LEVEL=0
if echo "$DIFF" | grep -qE "(parent|super|inherit|extends|depth|level|nested)"; then
    MULTI_LEVEL=$((MULTI_LEVEL + 1))
fi
if echo "$DIFF" | grep -qE "(push|pop|stack|context|blocks\[|block_stack)"; then
    MULTI_LEVEL=$((MULTI_LEVEL + 1))
fi
if echo "$DIFF" | grep -qE "(render|resolve|compile|nodelist)"; then
    MULTI_LEVEL=$((MULTI_LEVEL + 1))
fi
case $MULTI_LEVEL in
    3) echo "[x] Fix addresses multi-level block resolution"; SCORE=$((SCORE + 25)) ;;
    2) echo "[~] Partial multi-level fix ($MULTI_LEVEL/3)"; SCORE=$((SCORE + 15)) ;;
    1) echo "[~] Minimal multi-level fix ($MULTI_LEVEL/3)"; SCORE=$((SCORE + 10)) ;;
    *) echo "[ ] Multi-level inheritance not addressed" ;;
esac

# Check 3 (20): Changes scoped to django/template/
SCOPE_OK=true
if [ -n "$ALL_CHANGED" ]; then
    while IFS= read -r f; do
        case "$f" in
            django/template/*) ;;
            HISTORY.md) ;;
            "") ;;
            *) SCOPE_OK=false; echo "WARNING: change outside scope: $f" ;;
        esac
    done <<< "$(echo "$ALL_CHANGED" | sort -u)"
fi
if [ "$SCOPE_OK" = true ]; then
    echo "[x] Changes scoped to django/template/"
    SCORE=$((SCORE + 20))
else
    echo "[!] Changes outside django/template/"
fi

# Check 4 (25): Syntax valid
SYNTAX_OK=true
while IFS= read -r f; do
    case "$f" in
        django/template/*.py)
            if [ -f "$f" ]; then
                if ! python3 -c "import ast; ast.parse(open('$f').read())" 2>/dev/null; then
                    SYNTAX_OK=false
                    echo "[ ] Syntax error in $f"
                fi
            fi ;;
    esac
done <<< "$(echo "$ALL_CHANGED" | sort -u)"
if [ "$SYNTAX_OK" = true ]; then
    echo "[x] Python syntax valid"
    SCORE=$((SCORE + 25))
fi

REWARD=$(awk "BEGIN {printf \"%.2f\", $SCORE / 100}")
echo "$REWARD" > /logs/verifier/reward.txt
echo "Score: $REWARD"
