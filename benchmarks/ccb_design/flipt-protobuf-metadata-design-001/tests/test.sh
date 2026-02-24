#!/bin/bash
# Reward: checklist (0.0-1.0) — weighted correctness checks
# Verifies cross-language schema change: proto + Go server

set -e

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh


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

echo "Running enterprise task 5 verification..."

SCORE_NUMERATOR=0

# Check 1 (0.20): Proto schema has segment_match_type field
if grep -q "segment_match_type" rpc/flipt/evaluation/evaluation.proto 2>/dev/null; then
    # Check it's a proper field definition with field number
    if grep -qE "string\s+segment_match_type\s*=\s*[0-9]+" rpc/flipt/evaluation/evaluation.proto 2>/dev/null; then
        echo "[x] Proto schema has segment_match_type field with proper definition"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 20))
    else
        echo "[~] Proto schema mentions segment_match_type but not properly defined"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 10))
    fi
else
    echo "[ ] Proto schema does not have segment_match_type field"
fi

# Check 2 (0.20): Generated Go code has SegmentMatchType field
if grep -q "SegmentMatchType" rpc/flipt/evaluation/evaluation.pb.go 2>/dev/null; then
    # Check for both field and getter
    HAS_FIELD=false
    HAS_GETTER=false
    grep -qE "SegmentMatchType\s+string" rpc/flipt/evaluation/evaluation.pb.go && HAS_FIELD=true
    grep -q "GetSegmentMatchType" rpc/flipt/evaluation/evaluation.pb.go && HAS_GETTER=true

    if [ "$HAS_FIELD" = true ] && [ "$HAS_GETTER" = true ]; then
        echo "[x] Go generated code has SegmentMatchType field and getter"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 20))
    elif [ "$HAS_FIELD" = true ]; then
        echo "[~] Go generated code has SegmentMatchType field but no getter"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 12))
    else
        echo "[~] Go generated code mentions SegmentMatchType"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 8))
    fi
else
    echo "[ ] Go generated code does not have SegmentMatchType"
fi

# Check 3 (0.20): Server code populates the field
if git diff "$ORIGIN_REF..HEAD" -- internal/server/evaluation/evaluation.go 2>/dev/null | grep -qi "SegmentMatchType\|segment_match_type"; then
    echo "[x] Server code sets SegmentMatchType in evaluation response"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 20))
elif git diff -- internal/server/evaluation/evaluation.go 2>/dev/null | grep -qi "SegmentMatchType\|segment_match_type"; then
    echo "[x] Server code sets SegmentMatchType (unstaged)"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 20))
else
    echo "[ ] Server code does not populate SegmentMatchType"
fi

# Check 4 (0.15): Cross-language consistency (both proto AND Go changed)
PROTO_CHANGED=false
GO_SERVER_CHANGED=false
GO_GENERATED_CHANGED=false

if git diff "$ORIGIN_REF..HEAD" --name-only 2>/dev/null | grep -q "evaluation.proto"; then
    PROTO_CHANGED=true
elif git diff --name-only 2>/dev/null | grep -q "evaluation.proto"; then
    PROTO_CHANGED=true
fi

if git diff "$ORIGIN_REF..HEAD" --name-only 2>/dev/null | grep -q "evaluation.go"; then
    GO_SERVER_CHANGED=true
elif git diff --name-only 2>/dev/null | grep -q "evaluation.go"; then
    GO_SERVER_CHANGED=true
fi

if git diff "$ORIGIN_REF..HEAD" --name-only 2>/dev/null | grep -q "evaluation.pb.go"; then
    GO_GENERATED_CHANGED=true
elif git diff --name-only 2>/dev/null | grep -q "evaluation.pb.go"; then
    GO_GENERATED_CHANGED=true
fi

CROSS_LANG_COUNT=0
[ "$PROTO_CHANGED" = true ] && CROSS_LANG_COUNT=$((CROSS_LANG_COUNT + 1))
[ "$GO_SERVER_CHANGED" = true ] && CROSS_LANG_COUNT=$((CROSS_LANG_COUNT + 1))
[ "$GO_GENERATED_CHANGED" = true ] && CROSS_LANG_COUNT=$((CROSS_LANG_COUNT + 1))

if [ "$CROSS_LANG_COUNT" -ge 3 ]; then
    echo "[x] Cross-language change: proto + generated Go + server Go all modified"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 15))
elif [ "$CROSS_LANG_COUNT" -ge 2 ]; then
    echo "[~] Partial cross-language change ($CROSS_LANG_COUNT/3 file types)"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 8))
else
    echo "[ ] Not a cross-language change ($CROSS_LANG_COUNT/3 file types modified)"
fi

# Check 5 (0.25): Go compilation succeeds
echo "Running Go compilation check..."
if go build ./internal/server/evaluation/... 2>/logs/verifier/build_errors.txt; then
    echo "[x] Go compilation passed"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
else
    echo "[ ] Go compilation failed"
    head -20 /logs/verifier/build_errors.txt 2>/dev/null
fi

# Scope check: changes within allowed paths
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
            rpc/flipt/evaluation/*) ;;
            internal/server/evaluation/*) ;;
            *) OUTSIDE_SCOPE=1; echo "WARNING: change outside allowed scope: $f" ;;
        esac
    done <<< "$ALL_CHANGED"
fi
if [ "$OUTSIDE_SCOPE" -eq 0 ]; then
    echo "[x] All changes within allowed scope"
else
    echo "[!] Changes outside allowed scope"
fi

SCORE=$(awk "BEGIN {printf \"%.2f\", $SCORE_NUMERATOR / 100}")
echo "$SCORE" > /logs/verifier/reward.txt
echo ""
echo "[x] Tests completed - Score: $SCORE"
