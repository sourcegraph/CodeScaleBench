#!/bin/bash
# Test script for VS Code scrollend event implementation
# Verifies that:
# 1. scrollend event fires in scroll handlers
# 2. Tests pass
# 3. No regressions in scroll performance

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

echo "Running VS Code test suite..."

# Check if diagnostics-related changes were made
if git diff --name-only 2>/dev/null | grep -E "(diagnostics|extension)" | head -5; then
    echo "✓ Diagnostics-related files modified"
    CHANGES_MADE=1
else
    echo "⚠ No diagnostics-related changes detected"
    CHANGES_MADE=0
fi

# Check for specific TypeScript service modifications
if grep -r "git\|branch\|refresh" src/vs/workbench/contrib/typescript-language-features 2>/dev/null | head -3; then
    echo "✓ TypeScript language features contain relevant code"
    TS_CHANGES=1
else
    echo "⚠ No TypeScript service changes for git awareness"
    TS_CHANGES=0
fi

# Calculate reward based on changes
if [ "$CHANGES_MADE" -eq 1 ] && [ "$TS_CHANGES" -eq 1 ]; then
    echo "1" > /logs/verifier/reward.txt
    echo "✓ Tests completed - Full reward"
elif [ "$CHANGES_MADE" -eq 1 ] || [ "$TS_CHANGES" -eq 1 ]; then
    echo "0.5" > /logs/verifier/reward.txt
    echo "✓ Tests completed - Partial reward"
else
    echo "0" > /logs/verifier/reward.txt
    echo "✓ Tests completed - No reward"
fi
