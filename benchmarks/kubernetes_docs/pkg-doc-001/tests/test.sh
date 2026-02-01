#!/bin/bash
# Test script for pkg-doc-001: Container Manager Package Documentation
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

TARGET_FILE="pkg/kubelet/cm/doc.go"
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
if echo "$DOC_CONTENT" | grep -q "^package cm"; then
    echo "PASS: Valid Go package declaration"
    SCORE=$((SCORE + 1))
else
    echo "FAIL: Missing or incorrect package declaration"
fi

# Check 3: Mentions ContainerManager interface (1 point)
if echo "$DOC_CONTENT" | grep -qi "ContainerManager"; then
    echo "PASS: References ContainerManager interface"
    SCORE=$((SCORE + 1))
else
    echo "WARN: Does not reference ContainerManager interface"
fi

# Check 4: Mentions cgroup/resource management (1 point)
if echo "$DOC_CONTENT" | grep -qi "cgroup\|resource"; then
    echo "PASS: References cgroup/resource management"
    SCORE=$((SCORE + 1))
else
    echo "WARN: Does not reference cgroup or resource management"
fi

# Check 5: Mentions QoS (1 point)
if echo "$DOC_CONTENT" | grep -qi "QoS\|quality.of.service"; then
    echo "PASS: References QoS"
    SCORE=$((SCORE + 1))
else
    echo "WARN: Does not reference QoS"
fi

# Check 6: References subpackages verified in workspace (1 point)
REF_COUNT=0
for subpkg in "cpumanager" "memorymanager" "topologymanager" "devicemanager"; do
    if echo "$DOC_CONTENT" | grep -qi "$subpkg" && [ -d "pkg/kubelet/cm/$subpkg" ]; then
        REF_COUNT=$((REF_COUNT + 1))
    fi
done
if [ "$REF_COUNT" -ge 2 ]; then
    echo "PASS: References $REF_COUNT subpackages (verified in workspace)"
    SCORE=$((SCORE + 1))
else
    echo "WARN: Only $REF_COUNT verified subpackage references"
fi

# Check 7: Mentions platform differences (1 point)
if echo "$DOC_CONTENT" | grep -qi "linux\|windows\|platform"; then
    echo "PASS: References platform-specific behavior"
    SCORE=$((SCORE + 1))
else
    echo "WARN: Does not reference platform-specific behavior"
fi

# Check 8: References kubelet context (1 point)
if echo "$DOC_CONTENT" | grep -qi "kubelet"; then
    echo "PASS: References kubelet context"
    SCORE=$((SCORE + 1))
else
    echo "WARN: Does not reference kubelet"
fi

# Convert to decimal score
FINAL_SCORE=$(awk "BEGIN {printf \"%.1f\", $SCORE / $MAX_SCORE}")

echo "$FINAL_SCORE" > /logs/verifier/reward.txt
echo ""
echo "Tests completed - Score: $FINAL_SCORE (${SCORE}/${MAX_SCORE} checks passed)"
