#!/bin/bash
# Reward: checklist (0.0-1.0) — weighted correctness checks
# Verifies rate limit middleware follows actual Django patterns (not stale docs)

set -e

cd /workspace

mkdir -p /logs/verifier

git config --global --add safe.directory /workspace 2>/dev/null || true

# Guard: check for code changes (ignore the injected docs/architecture.md commit)
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
# Count commits after the injected doc commit (HEAD~1 is the doc injection)
if [ -n "$ORIGIN_REF" ]; then
    COMMIT_COUNT=$(git log --oneline "$ORIGIN_REF..HEAD" 2>/dev/null | wc -l)
    # Subtract 1 for the injected doc commit
    COMMIT_COUNT=$((COMMIT_COUNT - 1))
    [ "$COMMIT_COUNT" -lt 0 ] && COMMIT_COUNT=0
fi
echo "Change detection: unstaged=$UNSTAGED_COUNT staged=$STAGED_COUNT untracked=$UNTRACKED_COUNT commits=$COMMIT_COUNT"
if [ "$UNSTAGED_COUNT" -eq 0 ] && [ "$STAGED_COUNT" -eq 0 ] && [ "$UNTRACKED_COUNT" -eq 0 ] && [ "$COMMIT_COUNT" -eq 0 ]; then
    echo "No code changes detected (beyond injected docs)"
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

echo "Running enterprise task 2 verification..."

SCORE_NUMERATOR=0

# Check 1 (0.25): ratelimit.py exists with RateLimitMiddleware class
if [ -f "django/middleware/ratelimit.py" ]; then
    if grep -q "class RateLimitMiddleware" django/middleware/ratelimit.py; then
        echo "[x] ratelimit.py exists with RateLimitMiddleware class"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
    else
        echo "[~] ratelimit.py exists but missing RateLimitMiddleware class"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 10))
    fi
else
    echo "[ ] ratelimit.py not found"
fi

# Check 2 (0.30): Follows ACTUAL middleware pattern (get_response/__call__), NOT stale docs
# The stale docs say to use process(), BaseMiddleware, MiddlewareRegistry
FOLLOWS_REAL_PATTERN=false
FOLLOWS_STALE_PATTERN=false

if [ -f "django/middleware/ratelimit.py" ]; then
    # Real pattern: __init__ with get_response, __call__ or MiddlewareMixin
    if grep -qE "(def __init__.*get_response|MiddlewareMixin)" django/middleware/ratelimit.py; then
        if grep -qE "(def __call__|def process_request|def process_response)" django/middleware/ratelimit.py; then
            FOLLOWS_REAL_PATTERN=true
        fi
    fi

    # Stale pattern: MiddlewareRegistry, BaseMiddleware, process(), self.next()
    if grep -qE "(MiddlewareRegistry|BaseMiddleware|def process\(|self\.next\()" django/middleware/ratelimit.py; then
        FOLLOWS_STALE_PATTERN=true
    fi
fi

if [ "$FOLLOWS_REAL_PATTERN" = true ] && [ "$FOLLOWS_STALE_PATTERN" = false ]; then
    echo "[x] Follows actual Django middleware pattern (get_response + __call__)"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 30))
elif [ "$FOLLOWS_REAL_PATTERN" = true ] && [ "$FOLLOWS_STALE_PATTERN" = true ]; then
    echo "[~] Mixed: has real pattern but also stale doc artifacts"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 15))
elif [ "$FOLLOWS_STALE_PATTERN" = true ]; then
    echo "[!] Followed stale docs/architecture.md pattern — WRONG"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 0))
else
    echo "[ ] Cannot determine middleware pattern used"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 5))
fi

# Check 3 (0.20): Rate limiting logic (settings, IP tracking, 403 response)
RATE_FEATURES=0
if [ -f "django/middleware/ratelimit.py" ]; then
    grep -q "RATE_LIMIT_REQUESTS\|rate_limit" django/middleware/ratelimit.py && RATE_FEATURES=$((RATE_FEATURES + 1))
    grep -q "REMOTE_ADDR\|get_client_ip\|META" django/middleware/ratelimit.py && RATE_FEATURES=$((RATE_FEATURES + 1))
    grep -qE "HttpResponseForbidden|HttpResponse.*403|status.*403" django/middleware/ratelimit.py && RATE_FEATURES=$((RATE_FEATURES + 1))
    grep -qE "from django\.(conf|http)" django/middleware/ratelimit.py && RATE_FEATURES=$((RATE_FEATURES + 1))
fi

case $RATE_FEATURES in
    4) echo "[x] All rate limiting features present (settings, IP, 403, imports)"
       SCORE_NUMERATOR=$((SCORE_NUMERATOR + 20)) ;;
    3) echo "[~] Most rate limiting features present ($RATE_FEATURES/4)"
       SCORE_NUMERATOR=$((SCORE_NUMERATOR + 15)) ;;
    2) echo "[~] Some rate limiting features present ($RATE_FEATURES/4)"
       SCORE_NUMERATOR=$((SCORE_NUMERATOR + 10)) ;;
    *) echo "[ ] Rate limiting logic incomplete ($RATE_FEATURES/4)" ;;
esac

# Check 4 (0.25): Python syntax valid + changes scoped to django/middleware/
SYNTAX_OK=false
SCOPE_OK=false

if [ -f "django/middleware/ratelimit.py" ]; then
    if python3 -c "import ast; ast.parse(open('django/middleware/ratelimit.py').read())" 2>/logs/verifier/syntax_errors.txt; then
        echo "[x] Python syntax valid"
        SYNTAX_OK=true
    else
        echo "[ ] Python syntax errors found"
    fi
fi

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
            django/middleware/*) ;;
            docs/architecture.md) ;; # Injected by Dockerfile, ignore
            *) OUTSIDE_SCOPE=1; echo "WARNING: change outside django/middleware/: $f" ;;
        esac
    done <<< "$ALL_CHANGED"
fi
if [ "$OUTSIDE_SCOPE" -eq 0 ]; then
    SCOPE_OK=true
    echo "[x] All changes within django/middleware/"
fi

if [ "$SYNTAX_OK" = true ] && [ "$SCOPE_OK" = true ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
elif [ "$SYNTAX_OK" = true ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 15))
    echo "[!] Changes outside django/middleware/"
elif [ "$SCOPE_OK" = true ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 10))
fi

SCORE=$(awk "BEGIN {printf \"%.2f\", $SCORE_NUMERATOR / 100}")
echo "$SCORE" > /logs/verifier/reward.txt
echo ""
echo "[x] Tests completed - Score: $SCORE"
