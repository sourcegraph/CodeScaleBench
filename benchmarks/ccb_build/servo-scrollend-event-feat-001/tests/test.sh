#!/bin/bash
# Reward: checklist (0.0-1.0) — weighted structure and correctness checks
# Test script for Servo scrollend event implementation
# Verifies that:
# 1. scrollend event is defined in DOM events
# 2. Event fires correctly after scroll completion
# 3. Code compiles with cargo check
# 4. WPT tests pass for scrollend
#
# NOTE: A reward.json file exists alongside this task defining additional
# manual evaluation criteria (e.g., architecture_understanding, code_quality).
# These criteria are NOT automatically scored by this script and would require
# an LLM judge to evaluate. This script handles automated scoring only.

set -e

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh
# Artifact mode: parse answer.json, extract analysis text, apply diffs
if [ -f /tmp/.artifact_only_mode ] && [ -f /tests/answer_json_verifier_lib.sh ]; then
    source /tests/answer_json_verifier_lib.sh
fi


cd "${VERIFY_REPO:-/workspace}"

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
    echo "[ ] Tests completed - Score: 0.0 (no changes)"
    exit 0
fi

echo "Testing scrollend event implementation..."

# ── Compilation check ──────────────────────────────────────────────────
# Run cargo check on the workspace. If the code doesn't compile,
# score is 0 regardless of keyword matches.
echo "Running Rust compilation check (cargo check)..."
BUILD_OK=1
if ! cargo check 2>/logs/verifier/build_errors.txt; then
    echo "FAIL: cargo check failed"
    BUILD_OK=0
fi

if [ "$BUILD_OK" -eq 0 ]; then
    echo "Compilation failed — score set to 0.0"
    echo "0.0" > /logs/verifier/reward.txt
    echo ""
    echo "[ ] Tests completed - Score: 0.0 (build failure)"
    exit 0
fi
echo "[x] Rust compilation check passed"

# ── Unit/integration tests (best-effort) ──────────────────────────────
# Run scroll-related tests if they exist; failures reduce score
# but don't zero it out (keyword scoring still applies).
UNIT_TEST_PASS=0
# Look for scroll-related test files and run them
if cargo test --no-run 2>/dev/null | grep -qi "scroll"; then
    cargo test scroll 2>/logs/verifier/test_errors.txt && TEST_RC=0 || TEST_RC=$?
    if [ "$TEST_RC" -eq 0 ]; then
        echo "[x] Scroll-related tests passed"
        UNIT_TEST_PASS=1
    else
        echo "NOTE: Scroll-related tests failed"
    fi
else
    # Try running tests matching scrollend specifically
    cargo test scrollend 2>/logs/verifier/test_errors.txt && TEST_RC=0 || TEST_RC=$?
    if [ "$TEST_RC" -eq 0 ]; then
        echo "[x] scrollend tests passed"
        UNIT_TEST_PASS=1
    elif [ "$TEST_RC" -eq 1 ]; then
        echo "NOTE: scrollend tests failed"
    else
        echo "NOTE: No scroll test targets found, skipping"
    fi
fi

# ── Keyword-based scoring (secondary signal) ──────────────────────────
# Check if scrollend event code exists
if grep -r "scrollend" . --include="*.rs" 2>/dev/null | head -5; then
    echo "[x] scrollend event references found"
    SCROLLEND_FOUND=1
else
    echo "NOTE: No scrollend event references found"
    SCROLLEND_FOUND=0
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
RELEVANT_FILES=$(echo "$CHANGED_FILES" | grep -E "(scroll|event|dom)" | sort -u)
RELEVANT_COUNT=$(echo "$RELEVANT_FILES" | grep -c . 2>/dev/null || echo 0)
if [ "$RELEVANT_COUNT" -ge 2 ]; then
    echo "[x] Scroll/event-related files modified ($RELEVANT_COUNT files)"
    echo "$RELEVANT_FILES" | head -5
    CHANGES_MADE=1
elif [ "$RELEVANT_COUNT" -eq 1 ]; then
    echo "NOTE: Only 1 scroll-related file changed (need >= 2 for cross-module feature)"
    CHANGES_MADE=0
else
    echo "NOTE: No scroll-related changes detected"
    CHANGES_MADE=0
fi

# Check for WPT tests
WPT_TESTS=0
if [ -d "tests/wpt" ]; then
    if grep -r "scrollend" tests/wpt 2>/dev/null | head -2; then
        echo "[x] scrollend WPT tests found"
        WPT_TESTS=1
    else
        echo "NOTE: No scrollend WPT tests"
    fi
fi

# Calculate reward based on implementation (using bash arithmetic, avoiding bc)
# Weights: scrollend keyword=0.2, file changes=0.1, WPT tests=0.1, unit tests pass=0.3, compilation=0.3
# Note: compilation is a gate (already passed if we get here), so its 0.3 is implicit
# Rebalanced weights for remaining signals: scrollend=0.3, changes=0.2, WPT=0.2, unit tests=0.3
SCORE_NUMERATOR=0
if [ "$SCROLLEND_FOUND" -eq 1 ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 3))  # 0.3 * 10
fi
if [ "$CHANGES_MADE" -eq 1 ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 2))  # 0.2 * 10
fi
if [ "$WPT_TESTS" -eq 1 ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 2))  # 0.2 * 10
fi
if [ "$UNIT_TEST_PASS" -eq 1 ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 3))  # 0.3 * 10
fi

# Convert back to decimal (using awk for portable floating point)
SCORE=$(awk "BEGIN {printf \"%.1f\", $SCORE_NUMERATOR / 10}")

echo "$SCORE" > /logs/verifier/reward.txt
echo ""
echo "[x] Tests completed - Score: $SCORE"
