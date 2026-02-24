#!/bin/bash
# Reward: checklist (0.0-1.0) — weighted correctness checks
# Verifies interface method addition: FlagExists on ReadOnlyFlagStore

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

echo "Running dep-refactor-002 verification..."

SCORE_NUMERATOR=0

# Check 1 (0.20): Interface has FlagExists method
if grep -q 'FlagExists' internal/storage/storage.go 2>/dev/null; then
    if grep -qE 'FlagExists\(ctx context\.Context.*\(bool.*error\)' internal/storage/storage.go 2>/dev/null; then
        echo "[x] ReadOnlyFlagStore interface has FlagExists method with correct signature"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 20))
    else
        echo "[~] FlagExists found in storage.go but signature may be incorrect"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 10))
    fi
else
    echo "[ ] FlagExists not found in storage.go interface"
fi

# Check 2 (0.25): Implementations exist in concrete types
IMPL_COUNT=0
EXPECTED_IMPLS=("internal/storage/fs/store.go" "internal/storage/fs/snapshot.go" "internal/storage/sql/common/flag.go")

for impl_file in "${EXPECTED_IMPLS[@]}"; do
    if grep -q 'FlagExists' "$impl_file" 2>/dev/null; then
        if grep -qE 'func \(.*\) FlagExists\(' "$impl_file" 2>/dev/null; then
            IMPL_COUNT=$((IMPL_COUNT + 1))
            echo "  Found FlagExists implementation in $impl_file"
        fi
    fi
done

if [ "$IMPL_COUNT" -ge 3 ]; then
    echo "[x] All $IMPL_COUNT expected implementations found"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
elif [ "$IMPL_COUNT" -ge 2 ]; then
    echo "[~] $IMPL_COUNT/3 implementations found"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 17))
elif [ "$IMPL_COUNT" -ge 1 ]; then
    echo "[~] Only $IMPL_COUNT/3 implementations found"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 8))
else
    # Also check for implementations in unexpected locations
    OTHER_IMPLS=$(grep -rl 'func.*FlagExists(' internal/ 2>/dev/null | wc -l)
    if [ "$OTHER_IMPLS" -gt 0 ]; then
        echo "[~] FlagExists implementations found in non-standard locations ($OTHER_IMPLS files)"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 10))
    else
        echo "[ ] No FlagExists implementations found"
    fi
fi

# Check 3 (0.15): Implementations handle not-found errors
NOT_FOUND_HANDLING=0
for impl_file in "${EXPECTED_IMPLS[@]}"; do
    if grep -q 'FlagExists' "$impl_file" 2>/dev/null; then
        # Check that the implementation distinguishes not-found from real errors
        if grep -A 15 'func.*FlagExists(' "$impl_file" 2>/dev/null | grep -qiE 'not.?found\|ErrNotFound\|NotFound'; then
            NOT_FOUND_HANDLING=$((NOT_FOUND_HANDLING + 1))
        fi
    fi
done

if [ "$NOT_FOUND_HANDLING" -ge 2 ]; then
    echo "[x] $NOT_FOUND_HANDLING implementations handle not-found errors"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 15))
elif [ "$NOT_FOUND_HANDLING" -ge 1 ]; then
    echo "[~] Only $NOT_FOUND_HANDLING implementations handle not-found errors"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 8))
else
    echo "[ ] No not-found error handling detected"
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
