#!/bin/bash
# Test script for applyconfig-doc-001: Apply Configurations Package Documentation
# Signal 1: File-reference validation (harbor reward)

set -e

cd /workspace

# Create log directories
mkdir -p /logs/verifier

# Fix git safe.directory
git config --global --add safe.directory /workspace 2>/dev/null || true

# Guard: if no code changes were made, the agent didn't execute successfully
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
elif git rev-parse FETCH_HEAD >/dev/null 2>&1; then
    COMMIT_COUNT=$(git log --oneline FETCH_HEAD..HEAD 2>/dev/null | wc -l)
else
    TOTAL_COMMITS=$(git log --oneline 2>/dev/null | wc -l)
    if [ "$TOTAL_COMMITS" -gt 1 ]; then
        COMMIT_COUNT=$((TOTAL_COMMITS - 1))
    fi
fi
echo "Change detection: unstaged=$UNSTAGED_COUNT staged=$STAGED_COUNT untracked=$UNTRACKED_COUNT commits=$COMMIT_COUNT"
if [ "$UNSTAGED_COUNT" -eq 0 ] && [ "$STAGED_COUNT" -eq 0 ] && [ "$UNTRACKED_COUNT" -eq 0 ] && [ "$COMMIT_COUNT" -eq 0 ]; then
    echo "No code changes detected - agent did not execute successfully"
    echo "0.0" > /logs/verifier/reward.txt
    echo ""
    echo "Tests completed - Score: 0.0 (no changes)"
    exit 0
fi

TARGET_FILE="staging/src/k8s.io/client-go/applyconfigurations/doc.go"
echo "Evaluating ${TARGET_FILE}..."

SCORE=0
MAX_SCORE=10

# Check 1: File exists (2 points)
if [ -f "$TARGET_FILE" ]; then
    echo "PASS: ${TARGET_FILE} exists"
    SCORE=$((SCORE + 2))
else
    echo "FAIL: ${TARGET_FILE} not found"
    echo "0.0" > /logs/verifier/reward.txt
    echo ""
    echo "Tests completed - Score: 0.0 (file not created)"
    exit 0
fi

DOC_CONTENT=$(cat "$TARGET_FILE")

# Check 2: Valid Go package declaration (1 point)
if echo "$DOC_CONTENT" | grep -q "^package applyconfigurations"; then
    echo "PASS: Valid Go package declaration"
    SCORE=$((SCORE + 1))
else
    echo "FAIL: Missing or incorrect package declaration"
fi

# Check 3: Mentions Server-side Apply (1 point)
if echo "$DOC_CONTENT" | grep -qi "Server-side Apply\|server.side apply\|SSA"; then
    echo "PASS: References Server-side Apply"
    SCORE=$((SCORE + 1))
else
    echo "WARN: Does not reference Server-side Apply"
fi

# Check 4: Explains zero-value / pointer problem (1 point)
if echo "$DOC_CONTENT" | grep -qi "pointer\|zero.value\|optional"; then
    echo "PASS: References pointer/zero-value problem"
    SCORE=$((SCORE + 1))
else
    echo "WARN: Does not explain pointer/zero-value problem"
fi

# Check 5: Mentions With functions (1 point)
if echo "$DOC_CONTENT" | grep -qi "With.*function\|With.*method\|WithSpec\|WithName\|With<"; then
    echo "PASS: References With builder functions"
    SCORE=$((SCORE + 1))
else
    echo "WARN: Does not reference With builder functions"
fi

# Check 6: Mentions FieldManager (1 point)
if echo "$DOC_CONTENT" | grep -qi "FieldManager\|field manager"; then
    echo "PASS: References FieldManager"
    SCORE=$((SCORE + 1))
else
    echo "WARN: Does not reference FieldManager"
fi

# Check 7: Mentions controller patterns (1 point)
if echo "$DOC_CONTENT" | grep -qi "controller\|reconcil"; then
    echo "PASS: References controller patterns"
    SCORE=$((SCORE + 1))
else
    echo "WARN: Does not reference controller patterns"
fi

# Check 8: References to typed client packages exist in workspace (1 point)
if echo "$DOC_CONTENT" | grep -qi "typed\|client-go/kubernetes" && [ -d "staging/src/k8s.io/client-go/kubernetes" ]; then
    echo "PASS: References typed client (verified: package exists)"
    SCORE=$((SCORE + 1))
else
    echo "WARN: Missing or unverifiable reference to typed client"
fi

# Convert to decimal score
FINAL_SCORE=$(awk "BEGIN {printf \"%.1f\", $SCORE / $MAX_SCORE}")

echo "$FINAL_SCORE" > /logs/verifier/reward.txt
echo ""
echo "Tests completed - Score: $FINAL_SCORE (${SCORE}/${MAX_SCORE} checks passed)"
