#!/bin/bash
# Reward: checklist (0.0-1.0) — weighted correctness checks
# Verifies function signature propagation: NewResource() + ctx parameter

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

echo "Running dep-refactor-001 verification..."

SCORE_NUMERATOR=0

# Check 1 (0.20): NewResource function signature has context.Context parameter
if grep -qE 'func NewResource\(ctx context\.Context' internal/storage/resource.go 2>/dev/null; then
    echo "[x] NewResource signature has ctx context.Context parameter"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 20))
elif grep -qE 'func NewResource\(.*context\.Context' internal/storage/resource.go 2>/dev/null; then
    echo "[~] NewResource has context.Context but not as 'ctx' first param"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 10))
else
    echo "[ ] NewResource signature not updated with context.Context"
fi

# Check 2 (0.25): Call sites updated (check for context argument in NewResource calls)
CALL_SITES_WITH_CTX=0
CALL_SITES_TOTAL=0
while IFS= read -r file; do
    count=$(grep -c 'NewResource(' "$file" 2>/dev/null || echo 0)
    ctx_count=$(grep -c 'NewResource(ctx\|NewResource(context\.' "$file" 2>/dev/null || echo 0)
    CALL_SITES_TOTAL=$((CALL_SITES_TOTAL + count))
    CALL_SITES_WITH_CTX=$((CALL_SITES_WITH_CTX + ctx_count))
done < <(grep -rl 'NewResource(' internal/ 2>/dev/null | grep -v resource.go || true)

if [ "$CALL_SITES_TOTAL" -gt 0 ]; then
    if [ "$CALL_SITES_WITH_CTX" -ge "$CALL_SITES_TOTAL" ]; then
        echo "[x] All $CALL_SITES_TOTAL call sites pass context ($CALL_SITES_WITH_CTX/$CALL_SITES_TOTAL)"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
    elif [ "$CALL_SITES_WITH_CTX" -gt 0 ]; then
        PARTIAL=$((25 * CALL_SITES_WITH_CTX / CALL_SITES_TOTAL))
        echo "[~] $CALL_SITES_WITH_CTX/$CALL_SITES_TOTAL call sites updated"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + PARTIAL))
    else
        echo "[ ] No call sites pass context"
    fi
else
    echo "[ ] No NewResource call sites found outside resource.go"
fi

# Check 3 (0.15): Multiple files modified (expect 8+)
FILES_CHANGED=0
if [ -n "$ORIGIN_REF" ]; then
    FILES_CHANGED=$(git diff --name-only "$ORIGIN_REF..HEAD" -- internal/ 2>/dev/null | wc -l)
fi
if [ "$FILES_CHANGED" -eq 0 ]; then
    FILES_CHANGED=$(git diff --name-only -- internal/ 2>/dev/null | wc -l)
fi

if [ "$FILES_CHANGED" -ge 8 ]; then
    echo "[x] $FILES_CHANGED files changed in internal/ (expected 8+)"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 15))
elif [ "$FILES_CHANGED" -ge 4 ]; then
    echo "[~] $FILES_CHANGED files changed (expected 8+, partial credit)"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 8))
elif [ "$FILES_CHANGED" -ge 1 ]; then
    echo "[~] Only $FILES_CHANGED files changed (expected 8+)"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 4))
else
    echo "[ ] No files changed in internal/"
fi

# Check 4 (0.10): Changes scoped to internal/ only
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
            internal/*) ;;
            *) OUTSIDE_SCOPE=1; echo "WARNING: change outside internal/: $f" ;;
        esac
    done <<< "$ALL_CHANGED"
fi
if [ "$OUTSIDE_SCOPE" -eq 0 ]; then
    echo "[x] All changes within internal/"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 10))
else
    echo "[!] Changes outside internal/"
fi

# Check 5 (0.30): Go compilation succeeds
echo "Running Go compilation check..."
if go build ./internal/... 2>/logs/verifier/build_errors.txt; then
    echo "[x] Go compilation passed"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 30))
else
    echo "[ ] Go compilation failed"
    head -20 /logs/verifier/build_errors.txt 2>/dev/null
fi

SCORE=$(awk "BEGIN {printf \"%.2f\", $SCORE_NUMERATOR / 100}")
echo "$SCORE" > /logs/verifier/reward.txt
echo ""
echo "[x] Tests completed - Score: $SCORE"
