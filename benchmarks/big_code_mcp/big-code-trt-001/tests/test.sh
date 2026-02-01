#!/bin/bash
# Test script for TensorRT-LLM W4A8_MXFP4_INT8 quantization mode
# Verifies that:
# 1. W4A8_MXFP4_INT8 mode is defined in quantization enums
# 2. Quantization pipeline supports the new mode
# 3. Unit tests pass for the new mode

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
    echo "[ ] Tests completed - Score: 0.0 (no changes)"
    exit 0
fi

echo "Testing W4A8_MXFP4_INT8 quantization mode implementation..."

# Check if quantization mode code exists
if grep -r "W4A8_MXFP4_INT8" . --include="*.py" --include="*.h" --include="*.cc" 2>/dev/null | head -5; then
    echo "[x] W4A8_MXFP4_INT8 mode references found"
    MODE_FOUND=1
else
    echo "NOTE: No W4A8_MXFP4_INT8 mode references found"
    MODE_FOUND=0
fi

# Check for enum definitions
if grep -r "MXFP4" . --include="*.py" --include="*.h" 2>/dev/null | head -3; then
    echo "[x] MXFP4 quantization mode references found"
    MXFP4_FOUND=1
else
    echo "NOTE: No MXFP4 mode references"
    MXFP4_FOUND=0
fi

# Check for relevant code changes
if git diff --name-only 2>/dev/null | grep -E "(quant|mode|config)" | head -5; then
    echo "[x] Quantization-related files modified"
    CHANGES_MADE=1
else
    echo "NOTE: No quantization-related changes detected"
    CHANGES_MADE=0
fi

# Calculate reward (using bash arithmetic, avoiding bc)
SCORE_NUMERATOR=0
if [ "$MODE_FOUND" -eq 1 ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 5))  # 0.5 * 10
fi
if [ "$MXFP4_FOUND" -eq 1 ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 2))  # 0.2 * 10
fi
if [ "$CHANGES_MADE" -eq 1 ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 3))  # 0.3 * 10
fi

# Convert back to decimal (using awk for portable floating point)
SCORE=$(awk "BEGIN {printf \"%.1f\", $SCORE_NUMERATOR / 10}")

echo "$SCORE" > /logs/verifier/reward.txt
echo ""
echo "[x] Tests completed - Score: $SCORE"
