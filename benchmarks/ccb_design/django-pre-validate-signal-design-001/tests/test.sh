#!/bin/bash
set -e

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

cd /workspace
mkdir -p /logs/verifier
git config --global --add safe.directory /workspace 2>/dev/null || true

# Change detection (subtract 1 for injected doc commit)
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

SCORE=0

# Check 1 (25): pre_validate signal defined in django/db/models/signals.py
if [ -f "django/db/models/signals.py" ]; then
    if grep -q "pre_validate" django/db/models/signals.py; then
        echo "[x] pre_validate signal found in signals.py"
        SCORE=$((SCORE + 25))
    else
        echo "[ ] pre_validate not found in signals.py"
    fi
else
    echo "[ ] django/db/models/signals.py not found"
fi

# Check 2 (30): Uses real Signal() pattern, NOT SignalRegistry
REAL_PATTERN=false
STALE_PATTERN=false
if grep -rq "Signal()" django/db/models/ 2>/dev/null; then
    REAL_PATTERN=true
fi
if grep -rqE "(SignalRegistry|registry\.register|registry\.dispatch)" django/db/models/ 2>/dev/null; then
    STALE_PATTERN=true
fi

if [ "$REAL_PATTERN" = true ] && [ "$STALE_PATTERN" = false ]; then
    echo "[x] Uses real Signal() pattern (not stale SignalRegistry)"
    SCORE=$((SCORE + 30))
elif [ "$REAL_PATTERN" = true ]; then
    echo "[~] Has Signal() but also stale SignalRegistry artifacts"
    SCORE=$((SCORE + 15))
elif [ "$STALE_PATTERN" = true ]; then
    echo "[!] Used stale SignalRegistry pattern from docs"
else
    echo "[ ] Could not determine signal pattern"
    SCORE=$((SCORE + 5))
fi

# Check 3 (20): Signal dispatch integrated into validation flow
DISPATCH_FOUND=false
if grep -rqE "(pre_validate\.send|pre_validate\.send_robust)" django/db/models/ 2>/dev/null; then
    echo "[x] pre_validate signal dispatched in model code"
    DISPATCH_FOUND=true
    SCORE=$((SCORE + 20))
elif grep -rq "pre_validate" django/db/models/__init__.py 2>/dev/null || \
     grep -rq "pre_validate" django/db/models/base.py 2>/dev/null; then
    echo "[~] pre_validate referenced but dispatch not confirmed"
    SCORE=$((SCORE + 10))
else
    echo "[ ] pre_validate not dispatched in model code"
fi

# Check 4 (25): Syntax valid + scoped to django/db/models/
SYNTAX_OK=false
SCOPE_OK=true
for f in $(git diff --name-only 2>/dev/null; git diff --cached --name-only 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null); do
    case "$f" in
        django/db/models/*) ;;
        docs/signals_architecture.md) ;;
        *) SCOPE_OK=false; echo "WARNING: change outside scope: $f" ;;
    esac
done

for pyf in $(find django/db/models/ -name "*.py" -newer docs/signals_architecture.md 2>/dev/null); do
    if ! python3 -c "import ast; ast.parse(open('$pyf').read())" 2>/dev/null; then
        echo "[ ] Syntax error in $pyf"
        SYNTAX_OK=false
        break
    fi
done
# If no syntax errors found in modified files, check signals.py specifically
if python3 -c "import ast; ast.parse(open('django/db/models/signals.py').read())" 2>/dev/null; then
    SYNTAX_OK=true
fi

if [ "$SYNTAX_OK" = true ] && [ "$SCOPE_OK" = true ]; then
    echo "[x] Syntax valid, changes scoped to django/db/models/"
    SCORE=$((SCORE + 25))
elif [ "$SYNTAX_OK" = true ]; then
    echo "[~] Syntax valid but changes outside scope"
    SCORE=$((SCORE + 15))
elif [ "$SCOPE_OK" = true ]; then
    echo "[~] Scoped correctly but syntax issues"
    SCORE=$((SCORE + 10))
fi

REWARD=$(awk "BEGIN {printf \"%.2f\", $SCORE / 100}")
echo "$REWARD" > /logs/verifier/reward.txt
echo ""
echo "Score: $REWARD"
