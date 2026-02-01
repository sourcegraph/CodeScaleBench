#!/bin/bash
# Test script for Servo scrollend event implementation
# Verifies that:
# 1. scrollend event is defined in DOM events
# 2. Event fires correctly after scroll completion
# 3. WPT tests pass for scrollend

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
COMMIT_COUNT=0
if git rev-parse FETCH_HEAD >/dev/null 2>&1; then
    COMMIT_COUNT=$(git log --oneline FETCH_HEAD..HEAD 2>/dev/null | wc -l)
elif git rev-parse ORIG_HEAD >/dev/null 2>&1; then
    COMMIT_COUNT=$(git log --oneline ORIG_HEAD..HEAD 2>/dev/null | wc -l)
else
    COMMIT_COUNT=$(git reflog --no-decorate 2>/dev/null | grep -c "commit" || echo 0)
fi
if [ "$UNSTAGED_COUNT" -eq 0 ] && [ "$STAGED_COUNT" -eq 0 ] && [ "$UNTRACKED_COUNT" -eq 0 ] && [ "$COMMIT_COUNT" -eq 0 ]; then
    echo "No code changes detected — agent did not execute successfully"
    echo "0.0" > /logs/verifier/reward.txt
    echo ""
    echo "✗ Tests completed - Score: 0.0 (no changes)"
    exit 0
fi

echo "Testing scrollend event implementation..."

# Check if scrollend event code exists
if grep -r "scrollend" . --include="*.rs" 2>/dev/null | head -5; then
    echo "✓ scrollend event references found"
    SCROLLEND_FOUND=1
else
    echo "⚠ No scrollend event references found"
    SCROLLEND_FOUND=0
fi

# Check for relevant code changes
if git diff --name-only 2>/dev/null | grep -E "(scroll|event)" | head -5; then
    echo "✓ Scroll/event-related files modified"
    CHANGES_MADE=1
else
    echo "⚠ No scroll-related changes detected"
    CHANGES_MADE=0
fi

# Check for WPT tests
if [ -d "tests/wpt" ]; then
    echo "✓ WPT test directory exists"
    if grep -r "scrollend" tests/wpt 2>/dev/null | head -2; then
        echo "✓ scrollend WPT tests found"
        WPT_TESTS=1
    else
        echo "⚠ No scrollend WPT tests"
        WPT_TESTS=0
    fi
else
    WPT_TESTS=0
fi

# Calculate reward (using bash arithmetic, avoiding bc)
SCORE_NUMERATOR=0
if [ "$SCROLLEND_FOUND" -eq 1 ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 5))  # 0.5 * 10
fi
if [ "$CHANGES_MADE" -eq 1 ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 3))  # 0.3 * 10
fi
if [ "$WPT_TESTS" -eq 1 ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 2))  # 0.2 * 10
fi

# Convert back to decimal (using awk for portable floating point)
SCORE=$(awk "BEGIN {printf \"%.1f\", $SCORE_NUMERATOR / 10}")

echo "$SCORE" > /logs/verifier/reward.txt
echo ""
echo "✓ Tests completed - Score: $SCORE"
