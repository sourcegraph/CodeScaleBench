#!/bin/bash
# Reward: checklist (0.0-1.0) — weighted structure and correctness checks
# Test script for Kubernetes NoScheduleNoTraffic taint effect
# Verifies that:
# 1. Taint effect constant is defined
# 2. Tests for the new effect pass
# 3. No regressions in existing taint logic
#
# NOTE: This task also ships a static rubric JSON file with additional manual
# evaluation criteria (e.g., architecture_understanding, code_quality).
# Those rubric criteria are descriptive only; this verifier scores automated
# repo-state checks and emits the canonical validation_result sidecar.

set -e

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh
# Artifact mode: parse answer.json, extract analysis text, apply diffs
if [ -f /tmp/.artifact_only_mode ] && [ -f /tests/answer_json_verifier_lib.sh ]; then
    source /tests/answer_json_verifier_lib.sh
fi

TASK_WORKDIR="${TASK_WORKDIR:-/workspace}"
TASK_REPO_ROOT="${TASK_REPO_ROOT:-${VERIFY_REPO:-$TASK_WORKDIR}}"
VERIFY_REPO="${VERIFY_REPO:-$TASK_REPO_ROOT}"
TASK_OUTPUT="${TASK_OUTPUT:-/workspace/answer.json}"
PASS_THRESHOLD="0.7"
ARTIFACT_REQUIRED=false
if [ "${ARTIFACT_ONLY:-false}" = "true" ]; then
    ARTIFACT_REQUIRED=true
fi

cd "$TASK_REPO_ROOT"

# Create log directories
mkdir -p /logs/verifier

TAINT_ADDED=0
CHANGES_MADE=0
TESTS_ADDED=0
BUILD_OK=0
UNIT_TEST_PASS=0

write_invalid_output() {
    local code="$1"
    local message="$2"
    python3 - "$code" "$message" "$TASK_OUTPUT" "$ARTIFACT_REQUIRED" "$PASS_THRESHOLD" <<'PYEOF'
import json
import sys

code, message, primary_path, required_artifact, pass_threshold = sys.argv[1:6]
payload = {
    "schema_version": "validation_result.v1alpha1",
    "status": "invalid_output",
    "scorable": False,
    "scorer_family": "repo_state_heuristic",
    "reward": 0.0,
    "pass_threshold": float(pass_threshold),
    "passed": False,
    "output_contract": {
        "mode": "answer_json_bridge",
        "primary_path": primary_path,
        "required_artifact": required_artifact == "true",
    },
    "sub_scores": {},
    "failure": {
        "code": code,
        "message": message,
        "stage": "output_validation",
    },
}
with open("/logs/verifier/validation_result.json", "w") as f:
    json.dump(payload, f, indent=2)
PYEOF
    echo "0.0" > /logs/verifier/reward.txt
}

write_scored_result() {
    local score="$1"
    local reason="${2:-}"
    VALIDATION_SCORE="$score" \
    VALIDATION_REASON="$reason" \
    UNSTAGED_COUNT="${UNSTAGED_COUNT:-0}" \
    STAGED_COUNT="${STAGED_COUNT:-0}" \
    UNTRACKED_COUNT="${UNTRACKED_COUNT:-0}" \
    COMMIT_COUNT="${COMMIT_COUNT:-0}" \
    python3 - "$TASK_OUTPUT" "$ARTIFACT_REQUIRED" "$PASS_THRESHOLD" <<'PYEOF'
import json
import os
import sys

primary_path, required_artifact, pass_threshold = sys.argv[1:4]
reward = float(os.environ.get("VALIDATION_SCORE", "0.0"))
threshold = float(pass_threshold)
checks = {
    "taint_added": float(os.environ.get("TAINT_ADDED", "0") or 0),
    "changes_made": float(os.environ.get("CHANGES_MADE", "0") or 0),
    "tests_added": float(os.environ.get("TESTS_ADDED", "0") or 0),
    "unit_test_pass": float(os.environ.get("UNIT_TEST_PASS", "0") or 0),
    "build_ok": float(os.environ.get("BUILD_OK", "0") or 0),
}
details = {
    "check_weights": {
        "taint_added": 0.3,
        "changes_made": 0.2,
        "tests_added": 0.2,
        "unit_test_pass": 0.3,
        "build_ok": "gating",
    },
    "change_detection": {
        "unstaged": int(os.environ.get("UNSTAGED_COUNT", "0") or 0),
        "staged": int(os.environ.get("STAGED_COUNT", "0") or 0),
        "untracked": int(os.environ.get("UNTRACKED_COUNT", "0") or 0),
        "commits": int(os.environ.get("COMMIT_COUNT", "0") or 0),
    },
}
reason = os.environ.get("VALIDATION_REASON")
if reason:
    details["reason"] = reason
payload = {
    "schema_version": "validation_result.v1alpha1",
    "status": "scored",
    "scorable": True,
    "scorer_family": "repo_state_heuristic",
    "reward": reward,
    "pass_threshold": threshold,
    "passed": reward >= threshold,
    "output_contract": {
        "mode": "answer_json_bridge",
        "primary_path": primary_path,
        "required_artifact": required_artifact == "true",
    },
    "sub_scores": {
        "checks": checks,
    },
    "failure": None,
    "details": details,
}
with open("/logs/verifier/validation_result.json", "w") as f:
    json.dump(payload, f, indent=2)
PYEOF
    echo "$score" > /logs/verifier/reward.txt
}

# Fix git safe.directory: the repo was cloned as root during Docker build,
# but the verifier may run as a different user. Without this, all git
# commands silently fail due to CVE-2022-24765 ownership checks.
git config --global --add safe.directory "$TASK_REPO_ROOT" 2>/dev/null || true

if [ "${ARTIFACT_ONLY:-false}" = "true" ] && [ ! -f "${ANSWER_JSON:-$TASK_OUTPUT}" ]; then
    echo "Required answer.json artifact missing at ${ANSWER_JSON:-$TASK_OUTPUT}"
    write_invalid_output "missing_required_output" \
        "answer.json not found at ${ANSWER_JSON:-$TASK_OUTPUT}"
    exit 0
fi

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
    write_scored_result "0.0" "no_code_changes"
    echo ""
    echo "[ ] Tests completed - Score: 0.0 (no changes)"
    exit 0
fi

echo "Running Kubernetes tests for taint effects..."

# ── Compilation check ──────────────────────────────────────────────────
# Build the packages most likely affected by taint-effect changes.
# If the code doesn't compile, score is 0 regardless of keyword matches.
echo "Running Go compilation check..."
BUILD_OK=1
if ! go build ./pkg/apis/core/... 2>/logs/verifier/build_errors.txt; then
    echo "FAIL: go build ./pkg/apis/core/... failed"
    BUILD_OK=0
fi
if ! go build ./pkg/scheduler/... 2>>/logs/verifier/build_errors.txt; then
    echo "FAIL: go build ./pkg/scheduler/... failed"
    BUILD_OK=0
fi
if ! go build ./pkg/kubelet/... 2>>/logs/verifier/build_errors.txt; then
    echo "FAIL: go build ./pkg/kubelet/... failed"
    BUILD_OK=0
fi

if [ "$BUILD_OK" -eq 0 ]; then
    echo "Compilation failed — score set to 0.0"
    write_scored_result "0.0" "build_failure"
    echo ""
    echo "[ ] Tests completed - Score: 0.0 (build failure)"
    exit 0
fi
echo "[x] Go compilation check passed"

# ── Unit tests (best-effort) ───────────────────────────────────────────
# Run taint-related tests if the package exists; failures reduce score
# but don't zero it out (keyword scoring still applies).
UNIT_TEST_PASS=1
timeout 600 go test ./pkg/apis/core/taint/... 2>/logs/verifier/test_errors.txt && TEST_RC=0 || TEST_RC=$?
if [ "$TEST_RC" -eq 0 ]; then
    echo "[x] Taint unit tests passed"
elif [ "$TEST_RC" -eq 1 ]; then
    echo "NOTE: Taint unit tests failed"
    UNIT_TEST_PASS=0
else
    # Exit code 2+ usually means package not found or build error
    echo "NOTE: No taint test package found, skipping"
fi

# ── Keyword-based scoring (secondary signal) ───────────────────────────
# Check if NoScheduleNoTraffic taint effect was added
if grep -r "NoScheduleNoTraffic" pkg/ 2>/dev/null | head -3; then
    echo "[x] NoScheduleNoTraffic taint effect found"
    TAINT_ADDED=1
else
    echo "NOTE: NoScheduleNoTraffic taint effect not found"
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
RELEVANT_FILES=$(echo "$CHANGED_FILES" | grep -E "(taint|scheduler|kubelet|endpoint)" | sort -u)
RELEVANT_COUNT=$(echo "$RELEVANT_FILES" | grep -c . 2>/dev/null || echo 0)
if [ "$RELEVANT_COUNT" -ge 2 ]; then
    echo "[x] Taint-related files modified ($RELEVANT_COUNT files)"
    echo "$RELEVANT_FILES" | head -5
    CHANGES_MADE=1
elif [ "$RELEVANT_COUNT" -eq 1 ]; then
    echo "NOTE: Only 1 taint-related file changed (need >= 2 for multi-module feature)"
    CHANGES_MADE=0
else
    echo "NOTE: No taint-related changes detected"
    CHANGES_MADE=0
fi

# Check for test additions (K8s tests are *_test.go files throughout pkg/ and staging/)
if grep -r "NoScheduleNoTraffic" --include="*_test.go" pkg/ staging/ test/ 2>/dev/null | head -3; then
    echo "[x] Tests for new taint effect found"
    TESTS_ADDED=1
else
    echo "NOTE: No tests for new taint effect"
    TESTS_ADDED=0
fi

# Calculate reward based on implementation (using bash arithmetic, avoiding bc)
# Weights: taint constant=0.3, file changes=0.2, tests added=0.2, unit tests pass=0.3
SCORE_NUMERATOR=0
if [ "$TAINT_ADDED" -eq 1 ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 3))  # 0.3 * 10
fi
if [ "$CHANGES_MADE" -eq 1 ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 2))  # 0.2 * 10
fi
if [ "$TESTS_ADDED" -eq 1 ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 2))  # 0.2 * 10
fi
if [ "$UNIT_TEST_PASS" -eq 1 ]; then
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 3))  # 0.3 * 10
fi

# Convert back to decimal (using awk for portable floating point)
SCORE=$(awk "BEGIN {printf \"%.1f\", $SCORE_NUMERATOR / 10}")

write_scored_result "$SCORE" "completed"
echo ""
echo "[x] Tests completed - Score: $SCORE"
