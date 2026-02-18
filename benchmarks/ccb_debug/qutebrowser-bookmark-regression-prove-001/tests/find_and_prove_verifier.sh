#!/usr/bin/env bash
# Reward: find_and_prove (0.0-1.0) — 2-phase verification with majority-of-3 voting
#
# Phase 1 (0.5): Agent's regression test FAILS on buggy code (>=2 of 3 runs fail)
# Phase 2 (0.5): Agent's regression test PASSES after applying reference patch (>=2 of 3 runs pass)
#
# Environment variables (set by each task's test.sh before sourcing):
#   AGENT_TEST_PATH   — path to agent-written test (default: /workspace/regression_test.py)
#   REFERENCE_PATCH   — path to known-good patch (default: /tests/reference_fix.patch)
#   TEST_COMMAND       — command to run the test (default: python3 -m pytest)
#   PATCH_APPLY_DIR   — directory to apply patch in (default: /workspace)

set -euo pipefail

# --- Defaults ---
AGENT_TEST_PATH="${AGENT_TEST_PATH:-/workspace/regression_test.py}"
REFERENCE_PATCH="${REFERENCE_PATCH:-/tests/reference_fix.patch}"
TEST_COMMAND="${TEST_COMMAND:-python3 -m pytest}"
PATCH_APPLY_DIR="${PATCH_APPLY_DIR:-/workspace}"

# --- Logging setup ---
LOG_DIR="/logs/verifier"
mkdir -p "$LOG_DIR"

PHASE1_LOG="$LOG_DIR/phase1.log"
PHASE2_LOG="$LOG_DIR/phase2.log"
SUMMARY_LOG="$LOG_DIR/summary.log"
REWARD_FILE="$LOG_DIR/reward.txt"

# --- Helper: write final score and exit ---
write_score() {
    local score="$1"
    echo "$score" > "$REWARD_FILE"
    echo "=== FINAL SCORE: $score ===" >> "$SUMMARY_LOG"
    echo "$score"
    exit 0
}

# --- Edge case: agent test does not exist or is empty ---
if [[ ! -f "$AGENT_TEST_PATH" ]]; then
    echo "ERROR: Agent test not found at $AGENT_TEST_PATH" >> "$SUMMARY_LOG"
    write_score "0.0"
fi

if [[ ! -s "$AGENT_TEST_PATH" ]]; then
    echo "ERROR: Agent test is empty at $AGENT_TEST_PATH" >> "$SUMMARY_LOG"
    write_score "0.0"
fi

echo "=== Find and Prove Verifier ===" > "$SUMMARY_LOG"
echo "AGENT_TEST_PATH=$AGENT_TEST_PATH" >> "$SUMMARY_LOG"
echo "REFERENCE_PATCH=$REFERENCE_PATCH" >> "$SUMMARY_LOG"
echo "TEST_COMMAND=$TEST_COMMAND" >> "$SUMMARY_LOG"
echo "PATCH_APPLY_DIR=$PATCH_APPLY_DIR" >> "$SUMMARY_LOG"
echo "" >> "$SUMMARY_LOG"

# --- Phase 1: Test should FAIL on buggy code (>=2 of 3 fail) ---
echo "=== PHASE 1: Verify test fails on buggy code ===" >> "$SUMMARY_LOG"
echo "=== PHASE 1: Verify test fails on buggy code ===" > "$PHASE1_LOG"

phase1_failures=0
for run in 1 2 3; do
    echo "--- Phase 1, run $run ---" >> "$PHASE1_LOG"
    set +e
    timeout 60 $TEST_COMMAND "$AGENT_TEST_PATH" >> "$PHASE1_LOG" 2>&1
    exit_code=$?
    set -e

    if [[ $exit_code -ne 0 ]]; then
        phase1_failures=$((phase1_failures + 1))
        echo "Run $run: FAILED (exit $exit_code) — expected" >> "$PHASE1_LOG"
    else
        echo "Run $run: PASSED (exit 0) — unexpected" >> "$PHASE1_LOG"
    fi
done

phase1_pass=0
if [[ $phase1_failures -ge 2 ]]; then
    phase1_pass=1
    echo "Phase 1 PASSED: $phase1_failures/3 runs failed (>=2 required)" >> "$SUMMARY_LOG"
else
    echo "Phase 1 FAILED: only $phase1_failures/3 runs failed (<2 required)" >> "$SUMMARY_LOG"
fi

# --- Edge case: no reference patch ---
if [[ ! -f "$REFERENCE_PATCH" ]]; then
    echo "WARNING: Reference patch not found at $REFERENCE_PATCH — skipping Phase 2" >> "$SUMMARY_LOG"
    if [[ $phase1_pass -eq 1 ]]; then
        write_score "0.5"
    else
        write_score "0.0"
    fi
fi

# --- Phase 2: Apply patch, test should PASS (>=2 of 3 pass) ---
echo "=== PHASE 2: Verify test passes after fix ===" >> "$SUMMARY_LOG"
echo "=== PHASE 2: Verify test passes after fix ===" > "$PHASE2_LOG"

# Apply the reference patch
echo "Applying patch: git apply $REFERENCE_PATCH in $PATCH_APPLY_DIR" >> "$PHASE2_LOG"
set +e
(cd "$PATCH_APPLY_DIR" && git apply "$REFERENCE_PATCH") >> "$PHASE2_LOG" 2>&1
apply_exit=$?
set -e

if [[ $apply_exit -ne 0 ]]; then
    echo "ERROR: Patch application failed (exit $apply_exit)" >> "$PHASE2_LOG"
    echo "ERROR: Patch application failed — scoring Phase 1 only" >> "$SUMMARY_LOG"
    if [[ $phase1_pass -eq 1 ]]; then
        write_score "0.5"
    else
        write_score "0.0"
    fi
fi

phase2_passes=0
for run in 1 2 3; do
    echo "--- Phase 2, run $run ---" >> "$PHASE2_LOG"
    set +e
    timeout 60 $TEST_COMMAND "$AGENT_TEST_PATH" >> "$PHASE2_LOG" 2>&1
    exit_code=$?
    set -e

    if [[ $exit_code -eq 0 ]]; then
        phase2_passes=$((phase2_passes + 1))
        echo "Run $run: PASSED (exit 0) — expected" >> "$PHASE2_LOG"
    else
        echo "Run $run: FAILED (exit $exit_code) — unexpected" >> "$PHASE2_LOG"
    fi
done

phase2_pass=0
if [[ $phase2_passes -ge 2 ]]; then
    phase2_pass=1
    echo "Phase 2 PASSED: $phase2_passes/3 runs passed (>=2 required)" >> "$SUMMARY_LOG"
else
    echo "Phase 2 FAILED: only $phase2_passes/3 runs passed (<2 required)" >> "$SUMMARY_LOG"
fi

# --- Compute final score ---
score="0.0"
if [[ $phase1_pass -eq 1 && $phase2_pass -eq 1 ]]; then
    score="1.0"
elif [[ $phase1_pass -eq 1 ]]; then
    score="0.5"
elif [[ $phase2_pass -eq 1 ]]; then
    score="0.5"
fi

write_score "$score"
