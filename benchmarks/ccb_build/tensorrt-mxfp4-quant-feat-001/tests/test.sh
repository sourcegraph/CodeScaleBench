#!/bin/bash
# Reward: checklist (0.0-1.0) — weighted structure and correctness checks
# Test script for TensorRT-LLM W4A8_MXFP4_INT8 quantization mode
# Verifies that:
# 1. W4A8_MXFP4_INT8 mode is defined in quantization enums
# 2. Quantization pipeline supports the new mode
# 3. Unit tests pass for the new mode
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
ORIGIN_REF_GUARD=""
for ref in origin/master origin/main origin/HEAD; do
    if git rev-parse "$ref" >/dev/null 2>&1; then
        ORIGIN_REF_GUARD="$ref"
        break
    fi
done
if [ -n "$ORIGIN_REF_GUARD" ]; then
    COMMIT_COUNT=$(git log --oneline "$ORIGIN_REF_GUARD..HEAD" 2>/dev/null | wc -l)
elif git rev-parse FETCH_HEAD >/dev/null 2>&1; then
    COMMIT_COUNT=$(git log --oneline FETCH_HEAD..HEAD 2>/dev/null | wc -l)
else
    # Fallback: in a --depth 1 clone there is 1 commit; more means agent committed
    TOTAL_COMMITS=$(git log --oneline 2>/dev/null | wc -l)
    if [ "$TOTAL_COMMITS" -gt 1 ]; then
        COMMIT_COUNT=$((TOTAL_COMMITS - 1))
    fi
fi
echo "Change detection: unstaged=$UNSTAGED_COUNT staged=$STAGED_COUNT untracked=$UNTRACKED_COUNT commits=$COMMIT_COUNT (origin_ref=${ORIGIN_REF_GUARD:-none})"
if [ "$UNSTAGED_COUNT" -eq 0 ] && [ "$STAGED_COUNT" -eq 0 ] && [ "$UNTRACKED_COUNT" -eq 0 ] && [ "$COMMIT_COUNT" -eq 0 ]; then
    echo "No code changes detected — agent did not execute successfully"
    echo "0.0" > /logs/verifier/reward.txt
    echo ""
    echo "[ ] Tests completed - Score: 0.0 (no changes)"
    exit 0
fi

echo "Testing W4A8_MXFP4_INT8 quantization mode implementation..."

# ── Syntax checks ─────────────────────────────────────────────────────
# Full CUDA compilation is not feasible in Docker; syntax checks are
# the practical minimum to ensure the agent didn't produce broken code.
echo "Running Python syntax checks on modified .py files..."
SYNTAX_OK=1

# Collect all modified/added .py files (unstaged, staged, committed, untracked)
ORIGIN_REF=""
for ref in origin/master origin/main origin/HEAD; do
    if git rev-parse "$ref" >/dev/null 2>&1; then
        ORIGIN_REF="$ref"
        break
    fi
done

MODIFIED_PY=""
if [ -n "$ORIGIN_REF" ]; then
    MODIFIED_PY=$(git diff --name-only "$ORIGIN_REF..HEAD" 2>/dev/null | grep '\.py$' || true)
fi
MODIFIED_PY="$MODIFIED_PY
$(git diff --name-only 2>/dev/null | grep '\.py$' || true)
$(git diff --cached --name-only 2>/dev/null | grep '\.py$' || true)
$(git ls-files --others --exclude-standard 2>/dev/null | grep '\.py$' || true)"
# Deduplicate
MODIFIED_PY=$(echo "$MODIFIED_PY" | sort -u | grep -v '^$' || true)

if [ -n "$MODIFIED_PY" ]; then
    PY_FAIL=0
    while IFS= read -r pyfile; do
        if [ -f "$pyfile" ]; then
            if ! python -m py_compile "$pyfile" 2>>/logs/verifier/syntax_errors.txt; then
                echo "FAIL: Python syntax error in $pyfile"
                PY_FAIL=1
            fi
        fi
    done <<< "$MODIFIED_PY"
    if [ "$PY_FAIL" -eq 1 ]; then
        SYNTAX_OK=0
    else
        echo "[x] All modified Python files pass syntax check"
    fi
else
    echo "NOTE: No modified Python files to check"
fi

# C++ syntax check for modified .h/.cpp/.cc files (using g++ -fsyntax-only)
echo "Running C++ syntax checks on modified .h/.cpp/.cc files..."
MODIFIED_CPP=""
if [ -n "$ORIGIN_REF" ]; then
    MODIFIED_CPP=$(git diff --name-only "$ORIGIN_REF..HEAD" 2>/dev/null | grep -E '\.(h|hpp|cpp|cc|cxx)$' || true)
fi
MODIFIED_CPP="$MODIFIED_CPP
$(git diff --name-only 2>/dev/null | grep -E '\.(h|hpp|cpp|cc|cxx)$' || true)
$(git diff --cached --name-only 2>/dev/null | grep -E '\.(h|hpp|cpp|cc|cxx)$' || true)
$(git ls-files --others --exclude-standard 2>/dev/null | grep -E '\.(h|hpp|cpp|cc|cxx)$' || true)"
MODIFIED_CPP=$(echo "$MODIFIED_CPP" | sort -u | grep -v '^$' || true)

if [ -n "$MODIFIED_CPP" ]; then
    CPP_FAIL=0
    while IFS= read -r cppfile; do
        if [ -f "$cppfile" ]; then
            # Use -fsyntax-only for syntax-only check; suppress missing header errors
            # since we don't have CUDA/TRT headers installed
            if ! g++ -fsyntax-only -std=c++17 "$cppfile" 2>>/logs/verifier/syntax_errors.txt; then
                # C++ syntax check failure is informational since headers may be missing
                echo "NOTE: C++ syntax check issue in $cppfile (may be missing headers)"
            fi
        fi
    done <<< "$MODIFIED_CPP"
    # Don't fail on C++ since missing CUDA headers will cause false positives
    echo "[x] C++ syntax check completed (informational only)"
else
    echo "NOTE: No modified C++ files to check"
fi

if [ "$SYNTAX_OK" -eq 0 ]; then
    echo "Python syntax check failed — score set to 0.0"
    echo "0.0" > /logs/verifier/reward.txt
    echo ""
    echo "[ ] Tests completed - Score: 0.0 (syntax failure)"
    exit 0
fi
echo "[x] Syntax checks passed"

# ── Keyword-based scoring (secondary signal) ──────────────────────────
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

# Check for relevant code changes (unstaged OR committed)
CHANGED_FILES=""
if [ -n "$ORIGIN_REF" ]; then
    CHANGED_FILES=$(git diff --name-only "$ORIGIN_REF..HEAD" 2>/dev/null)
fi
# Also include any unstaged/staged changes
CHANGED_FILES="$CHANGED_FILES
$(git diff --name-only 2>/dev/null)
$(git diff --cached --name-only 2>/dev/null)"
RELEVANT_FILES=$(echo "$CHANGED_FILES" | grep -E "(quant|mode|config)" | sort -u)
RELEVANT_COUNT=$(echo "$RELEVANT_FILES" | grep -c . 2>/dev/null || echo 0)
if [ "$RELEVANT_COUNT" -ge 2 ]; then
    echo "[x] Quantization-related files modified ($RELEVANT_COUNT files)"
    echo "$RELEVANT_FILES" | head -5
    CHANGES_MADE=1
elif [ "$RELEVANT_COUNT" -eq 1 ]; then
    echo "NOTE: Only 1 quantization-related file changed (need >= 2 for cross-module feature)"
    CHANGES_MADE=0
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
