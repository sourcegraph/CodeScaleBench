#!/bin/bash
set -euo pipefail

[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh
# Artifact mode: parse answer.json, extract analysis text, apply diffs
if [ -f /tmp/.artifact_only_mode ] && [ -f /tests/answer_json_verifier_lib.sh ]; then
    source /tests/answer_json_verifier_lib.sh
fi
SCORE=0
TOTAL=6
WORKSPACE="${VERIFY_REPO:-/workspace}"

TASK_OUTPUT="${TASK_OUTPUT:-/workspace/answer.json}"
PASS_THRESHOLD="0.6"
OUTPUT_CONTRACT_MODE="answer_json_bridge"
OUTPUT_PRIMARY_PATH="$TASK_OUTPUT"
ARTIFACT_REQUIRED=false
if [ "$OUTPUT_CONTRACT_MODE" = "repo_state" ]; then
    OUTPUT_PRIMARY_PATH=""
elif [ "${ARTIFACT_ONLY:-false}" = "true" ]; then
    ARTIFACT_REQUIRED=true
fi

write_invalid_output() {
    local code="$1"
    local message="$2"
    python3 - "$code" "$message" "$OUTPUT_CONTRACT_MODE" "$OUTPUT_PRIMARY_PATH" "$ARTIFACT_REQUIRED" "$PASS_THRESHOLD" <<'PYEOF'
import json
import sys

code, message, mode, primary_path, required_artifact, pass_threshold = sys.argv[1:7]
payload = {
    "schema_version": "validation_result.v1alpha1",
    "status": "invalid_output",
    "scorable": False,
    "scorer_family": "repo_state_heuristic",
    "reward": 0.0,
    "pass_threshold": float(pass_threshold),
    "passed": False,
    "output_contract": {
        "mode": mode,
        "primary_path": primary_path or None,
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
with open("/logs/verifier/reward.txt", "w") as f:
    f.write(f"{reward:.4f}\n")
PYEOF
    echo "0.0" > /logs/verifier/reward.txt
}

write_scored_result() {
    local score="$1"
    local reason="${2:-}"
    local passed_checks="${3:-}"
    local total_checks="${4:-}"
    env         VALIDATION_SCORE="$score"         VALIDATION_REASON="$reason"         VALIDATION_PASSED_CHECKS="$passed_checks"         VALIDATION_TOTAL_CHECKS="$total_checks"         CHANGE_UNSTAGED="${UNSTAGED_COUNT:-${UNSTAGED:-0}}"         CHANGE_STAGED="${STAGED_COUNT:-${STAGED:-0}}"         CHANGE_UNTRACKED="${UNTRACKED_COUNT:-${UNTRACKED:-0}}"         CHANGE_COMMITS="${COMMIT_COUNT:-${COMMITS:-0}}"         VALIDATION_OUTPUT_PATH="${VALIDATION_OUTPUT_PATH:-}"         python3 - "$OUTPUT_CONTRACT_MODE" "$OUTPUT_PRIMARY_PATH" "$ARTIFACT_REQUIRED" "$PASS_THRESHOLD" <<'PYEOF'
import json
import os
import sys

mode, primary_path, required_artifact, pass_threshold = sys.argv[1:5]
reward = float(os.environ.get("VALIDATION_SCORE", "0.0") or 0.0)
threshold = float(pass_threshold)
checks = {"heuristic_score": reward}
details = {}
reason = os.environ.get("VALIDATION_REASON")
if reason:
    details["reason"] = reason
passed_checks_raw = os.environ.get("VALIDATION_PASSED_CHECKS", "")
total_checks_raw = os.environ.get("VALIDATION_TOTAL_CHECKS", "")
if passed_checks_raw and total_checks_raw:
    try:
        passed_checks = float(passed_checks_raw)
        total_checks = float(total_checks_raw)
    except ValueError:
        passed_checks = None
        total_checks = None
    if passed_checks is not None and total_checks and total_checks > 0:
        checks["passed_checks_ratio"] = round(passed_checks / total_checks, 4)
        details["passed_checks"] = int(passed_checks) if passed_checks.is_integer() else passed_checks
        details["total_checks"] = int(total_checks) if total_checks.is_integer() else total_checks
change_detection = {
    "unstaged": int(os.environ.get("CHANGE_UNSTAGED", "0") or 0),
    "staged": int(os.environ.get("CHANGE_STAGED", "0") or 0),
    "untracked": int(os.environ.get("CHANGE_UNTRACKED", "0") or 0),
    "commits": int(os.environ.get("CHANGE_COMMITS", "0") or 0),
}
if any(change_detection.values()):
    checks["change_detected"] = 1.0
    details["change_detection"] = change_detection
else:
    # No-changes guard: env counts are all 0.  Verify via git that the agent
    # actually modified the repo — if not, force reward to 0.0 so tests that
    # pass on the unmodified repo don't produce false-positive scores.
    # Checks origin ref too, so agents that commit their work (e.g. OpenHands
    # runtime auto-commits) are not falsely penalised.
    import subprocess as _sp
    _verify = os.environ.get("VERIFY_REPO") or os.environ.get("TASK_REPO_ROOT") or "/workspace"
    try:
        _has_changes = False
        _d = _sp.run(["git", "diff", "HEAD", "--stat"], capture_output=True, text=True, cwd=_verify, timeout=5)
        if _d.stdout.strip():
            _has_changes = True
        _u = _sp.run(["git", "ls-files", "--others", "--exclude-standard"], capture_output=True, text=True, cwd=_verify, timeout=5)
        if _u.stdout.strip():
            _has_changes = True
        if not _has_changes:
            for _ref in ["origin/HEAD", "origin/main", "origin/master"]:
                _rv = _sp.run(["git", "rev-parse", "--verify", _ref], capture_output=True, text=True, cwd=_verify, timeout=5)
                if _rv.returncode == 0:
                    _cd = _sp.run(["git", "diff", _ref, "HEAD", "--stat"], capture_output=True, text=True, cwd=_verify, timeout=5)
                    if _cd.stdout.strip():
                        _has_changes = True
                    break
        if not _has_changes:
            reward = 0.0
            checks["no_changes_guard"] = 0.0
            details["no_changes_guard"] = "git confirmed zero agent changes"
    except Exception:
        pass
output_path = os.environ.get("VALIDATION_OUTPUT_PATH")
if output_path:
    details["output_path"] = output_path
payload = {
    "schema_version": "validation_result.v1alpha1",
    "status": "scored",
    "scorable": True,
    "scorer_family": "repo_state_heuristic",
    "reward": reward,
    "pass_threshold": threshold,
    "passed": reward >= threshold,
    "output_contract": {
        "mode": mode,
        "primary_path": primary_path or None,
        "required_artifact": required_artifact == "true",
    },
    "sub_scores": {"checks": checks},
    "failure": None,
}
if details:
    payload["details"] = details
with open("/logs/verifier/validation_result.json", "w") as f:
    json.dump(payload, f, indent=2)
with open("/logs/verifier/reward.txt", "w") as f:
    f.write(f"{reward:.4f}\n")
PYEOF
    # reward.txt now written by Python (respects no_changes_guard)
}


if [ "${ARTIFACT_ONLY:-false}" = "true" ] && [ "${ANSWER_JSON_MISSING:-false}" = "true" ]; then
    write_invalid_output "missing_required_output" \
        "answer.json not found at ${ANSWER_JSON:-$TASK_OUTPUT}"
    exit 0
fi
if [ "${ARTIFACT_ONLY:-false}" = "true" ] && [ "${ANSWER_JSON_NO_CHANGES:-false}" = "true" ]; then
    write_scored_result "0.0" "no_code_changes" "0" "$TOTAL"
    exit 0
fi
git config --global --add safe.directory "$WORKSPACE" 2>/dev/null || true

# Check 1: Old symbol removed from primary definition
OLD_DEF_COUNT=$( (grep -r 'class RequestFactory\|type RequestFactory struct\|def RequestFactory\|function RequestFactory' "$WORKSPACE/django/test/" "$WORKSPACE/tests/" 2>/dev/null | grep -v 'alias\|compat\|deprecated\|backward\|#.*RequestFactory\|//.*RequestFactory' || true) | wc -l)
if [ "$OLD_DEF_COUNT" -eq 0 ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: Old symbol definition removed"
else
    echo "FAIL: Old symbol \"RequestFactory\" still defined ($OLD_DEF_COUNT definitions found)"
fi

# Check 2: New symbol exists in definition
NEW_DEF_COUNT=$( (grep -r 'class TestRequestBuilder\|type TestRequestBuilder struct\|def TestRequestBuilder\|function TestRequestBuilder\|TestRequestBuilder' "$WORKSPACE/django/test/" "$WORKSPACE/tests/" 2>/dev/null || true) | wc -l)
if [ "$NEW_DEF_COUNT" -gt 0 ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: New symbol \"TestRequestBuilder\" found ($NEW_DEF_COUNT occurrences)"
else
    echo "FAIL: New symbol \"TestRequestBuilder\" not found"
fi

# Check 3: Old symbol reference count reduced (allowing aliases/deprecation)
OLD_REF_COUNT=$( (grep -r 'RequestFactory' "$WORKSPACE/django/test/" "$WORKSPACE/tests/" 2>/dev/null | grep -v 'test\|_test\|spec\|alias\|compat\|deprecated\|backward\|#.*RequestFactory\|//.*RequestFactory\|\.pyc' || true) | wc -l)
if [ "$OLD_REF_COUNT" -le 3 ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: Old symbol references minimized ($OLD_REF_COUNT remaining, max 3)"
else
    echo "FAIL: Too many old symbol references remain ($OLD_REF_COUNT, max 3)"
fi

# Check 4: New symbol used across multiple files
NEW_FILE_COUNT=$( (grep -rl 'TestRequestBuilder' "$WORKSPACE/django/test/" "$WORKSPACE/tests/" 2>/dev/null || true) | wc -l)
if [ "$NEW_FILE_COUNT" -ge 2 ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: New symbol used across $NEW_FILE_COUNT files"
else
    echo "FAIL: New symbol only in $NEW_FILE_COUNT files (need >= 2)"
fi

# Check 5: New symbol call sites meet threshold
NEW_REF_COUNT=$( (grep -r 'TestRequestBuilder' "$WORKSPACE/django/test/" "$WORKSPACE/tests/" 2>/dev/null || true) | wc -l)
if [ "$NEW_REF_COUNT" -ge 12 ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: New symbol has $NEW_REF_COUNT references (>= 12)"
else
    echo "FAIL: New symbol only has $NEW_REF_COUNT references (need >= 12)"
fi

# Check 6: Code changes were actually made (git diff check)
cd "$WORKSPACE"
CHANGED_FILES=$(git diff --name-only 2>/dev/null | wc -l)
STAGED_FILES=$(git diff --cached --name-only 2>/dev/null | wc -l)
# Only count committed files beyond the initial clone commit
TOTAL_COMMITS=$(git rev-list --count HEAD 2>/dev/null || echo 0)
COMMITTED_FILES=0
if [ "$TOTAL_COMMITS" -gt 1 ]; then
    FIRST_COMMIT=$(git rev-list --max-parents=0 HEAD 2>/dev/null | head -1)
    if [ -n "$FIRST_COMMIT" ]; then
        COMMITTED_FILES=$(git diff --name-only "$FIRST_COMMIT..HEAD" 2>/dev/null | wc -l)
    fi
fi
TOTAL_CHANGES=$((CHANGED_FILES + STAGED_FILES + COMMITTED_FILES))
if [ "$TOTAL_CHANGES" -ge 2 ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: Multiple files changed ($TOTAL_CHANGES)"
else
    echo "FAIL: Not enough files changed ($TOTAL_CHANGES, need >= 2)"
fi

echo ""
echo "Score: $SCORE / $TOTAL"

FINAL_SCORE=$(python3 -c "print($SCORE / $TOTAL)")
write_scored_result "$FINAL_SCORE" "" "$SCORE" "$TOTAL"
