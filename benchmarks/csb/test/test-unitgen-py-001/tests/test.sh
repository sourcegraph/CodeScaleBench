#!/bin/bash
# Reward: checklist (0.0-1.0) — Python unit test generation quality score
set -euo pipefail

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


mkdir -p /logs/verifier

if [ "${ARTIFACT_ONLY:-false}" = "true" ] && [ ! -f "${ANSWER_JSON:-$TASK_OUTPUT}" ]; then
    write_invalid_output "missing_required_output" \
        "answer.json not found at ${ANSWER_JSON:-$TASK_OUTPUT}"
    exit 0
fi

TARGET_FILE="/workspace/tests/test_cache_middleware.py"
ALT_FILE=$(find /workspace -name "test_cache*.py" -o -name "test_middleware*.py" 2>/dev/null | grep -v __pycache__ | head -1)
TEST_FILE="${ALT_FILE:-$TARGET_FILE}"

if [ ! -f "$TEST_FILE" ]; then
    echo "No test file found"
    write_scored_result "0.0" "missing_expected_output"
    exit 0
fi

echo "Scoring test file: $TEST_FILE"
VALIDATION_OUTPUT_PATH="$TEST_FILE"

SCORE=$(python3 - "$TEST_FILE" <<'PYEOF'
import sys, re

path = sys.argv[1]
try:
    content = open(path).read()
except Exception:
    print("0.0", end="")
    sys.exit(0)

score = 0.0

# Component 1: file presence (0.25)
score += 0.25

# Component 2: test count (0.35)
test_methods = re.findall(r'def\s+(test_\w+)\s*\(', content)
n = len(test_methods)
print(f"Test methods: {test_methods}", file=sys.stderr)
if n >= 8:
    score += 0.35
elif n >= 5:
    score += 0.25
elif n >= 3:
    score += 0.15
elif n >= 1:
    score += 0.08

# Component 3: edge case coverage (0.25)
edge_patterns = [
    r'non.cach|no.cach|not.cach|cannot.cach',
    r'POST|PUT|DELETE',
    r'private|no.store',
    r'Vary|vary',
    r'authenticated|login|logged',
    r'status.code|304|403|500',
    r'max.age|no.cache',
]
edge_hits = sum(1 for p in edge_patterns if re.search(p, content, re.IGNORECASE))
score += min(0.25, edge_hits * 0.05)
print(f"Edge case hits: {edge_hits}/7", file=sys.stderr)

# Component 4: Django TestCase usage (0.15)
if re.search(r'(TestCase|SimpleTestCase|RequestFactory|Client)', content):
    score += 0.15
    print("Django test infrastructure: PASS", file=sys.stderr)

print(f"Final score: {score:.2f}", file=sys.stderr)
print(f"{score:.2f}", end="")
PYEOF
)

write_scored_result "$SCORE"
echo "Score: $SCORE"
exit 0

# Dual-score: independently score both direct edits and answer.json
[ -f /tests/dual_score_lib.sh ] && source /tests/dual_score_lib.sh
