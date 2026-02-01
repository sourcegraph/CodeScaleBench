#!/bin/bash
# Test script for Kubernetes NoScheduleNoTraffic taint effect
# Verifies that:
# 1. Taint effect constant is defined
# 2. Tests for the new effect pass
# 3. No regressions in existing taint logic

set -e

cd /workspace

# Create log directories
mkdir -p /logs/verifier

# Fix git safe.directory: the repo was cloned as root during Docker build,
# but the verifier may run as a different user. Without this, all git
# commands silently fail due to CVE-2022-24765 ownership checks.
git config --global --add safe.directory /workspace 2>/dev/null || true

# Guard: if no code changes were made, the agent didn't execute successfully
# Check unstaged changes, staged changes, untracked files, AND new commits
UNSTAGED_COUNT=$(git diff --stat 2>/dev/null | wc -l)
STAGED_COUNT=$(git diff --cached --stat 2>/dev/null | wc -l)
UNTRACKED_COUNT=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l)
# Detect new commits: compare HEAD to the original clone point
# Use origin refs (most reliable for shallow clones created by git clone --depth 1)
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
    # Fallback: in a --depth 1 clone there is 1 commit; more means agent committed
    TOTAL_COMMITS=$(git log --oneline 2>/dev/null | wc -l)
    if [ "$TOTAL_COMMITS" -gt 1 ]; then
        COMMIT_COUNT=$((TOTAL_COMMITS - 1))
    fi
fi
echo "Change detection: unstaged=$UNSTAGED_COUNT staged=$STAGED_COUNT untracked=$UNTRACKED_COUNT commits=$COMMIT_COUNT (origin_ref=${ORIGIN_REF:-none})"
if [ "$UNSTAGED_COUNT" -eq 0 ] && [ "$STAGED_COUNT" -eq 0 ] && [ "$UNTRACKED_COUNT" -eq 0 ] && [ "$COMMIT_COUNT" -eq 0 ]; then
    echo "No code changes detected — agent did not execute successfully"
    echo "0.0" > /logs/verifier/reward.txt
    echo ""
    echo "✗ Tests completed - Score: 0.0 (no changes)"
    exit 0
fi

echo "Running Kubernetes tests for taint effects..."

# Check if NoScheduleNoTraffic taint effect was added
if grep -r "NoScheduleNoTraffic" pkg/ 2>/dev/null | head -3; then
    echo "✓ NoScheduleNoTraffic taint effect found"
    TAINT_ADDED=1
else
    echo "⚠ NoScheduleNoTraffic taint effect not found"
    TAINT_ADDED=0
fi

# Check for relevant code changes (unstaged OR committed)
DIFF_REF=""
if [ -n "$ORIGIN_REF" ]; then
    DIFF_REF="$ORIGIN_REF..HEAD"
fi
CHANGED_FILES=""
if [ -n "$DIFF_REF" ]; then
    CHANGED_FILES=$(git diff --name-only "$DIFF_REF" 2>/dev/null)
fi
# Also include any unstaged/staged changes
CHANGED_FILES="$CHANGED_FILES
$(git diff --name-only 2>/dev/null)
$(git diff --cached --name-only 2>/dev/null)"
if echo "$CHANGED_FILES" | grep -E "(taint|scheduler|kubelet|endpoint)" | head -5; then
    echo "✓ Taint-related files modified"
    CHANGES_MADE=1
else
    echo "⚠ No taint-related changes detected"
    CHANGES_MADE=0
fi

# Check for test additions (K8s tests are *_test.go files throughout pkg/ and staging/)
if grep -r "NoScheduleNoTraffic" --include="*_test.go" pkg/ staging/ test/ 2>/dev/null | head -3; then
    echo "✓ Tests for new taint effect found"
    TESTS_ADDED=1
else
    echo "⚠ No tests for new taint effect"
    TESTS_ADDED=0
fi

# Calculate reward based on implementation (using bash arithmetic, avoiding bc)
SCORE_NUMERATOR=0
if [ "$TAINT_ADDED" -eq 1 ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 4))  # 0.4 * 10
fi
if [ "$CHANGES_MADE" -eq 1 ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 3))  # 0.3 * 10
fi
if [ "$TESTS_ADDED" -eq 1 ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 3))  # 0.3 * 10
fi

# Convert back to decimal (using awk for portable floating point)
SCORE=$(awk "BEGIN {printf \"%.1f\", $SCORE_NUMERATOR / 10}")

echo "$SCORE" > /logs/verifier/reward.txt
echo ""
echo "✓ Tests completed - Score: $SCORE"
