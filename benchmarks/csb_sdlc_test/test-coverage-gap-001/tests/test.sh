#!/bin/bash
# Reward: checklist (0.0-1.0) — coverage gap analysis quality score
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
    import subprocess as _sp
    _verify = os.environ.get("VERIFY_REPO") or os.environ.get("TASK_REPO_ROOT") or "/workspace"
    try:
        _d = _sp.run(["git", "diff", "HEAD", "--stat"], capture_output=True, text=True, cwd=_verify, timeout=5)
        _u = _sp.run(["git", "ls-files", "--others", "--exclude-standard"], capture_output=True, text=True, cwd=_verify, timeout=5)
        if not _d.stdout.strip() and not _u.stdout.strip():
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
PYEOF
    echo "$score" > /logs/verifier/reward.txt
}


mkdir -p /logs/verifier

if [ "${ARTIFACT_ONLY:-false}" = "true" ] && [ ! -f "${ANSWER_JSON:-$TASK_OUTPUT}" ]; then
    write_invalid_output "missing_required_output" \
        "answer.json not found at ${ANSWER_JSON:-$TASK_OUTPUT}"
    exit 0
fi

OUTPUT_FILE="/workspace/coverage_analysis.md"
# In artifact mode, populate expected output from answer.json analysis
if [ "${ARTIFACT_ONLY:-false}" = "true" ] && [ -f "${ANALYSIS_TEXT_FILE:-}" ]; then
    cp "$ANALYSIS_TEXT_FILE" "/workspace/coverage_analysis.md"
    echo "[answer_json] Copied analysis text to /workspace/coverage_analysis.md"
fi

if [ ! -f "$OUTPUT_FILE" ]; then
    ALT=$(find /workspace -maxdepth 2 -name "*.md" ! -name "README*" 2>/dev/null | head -1)
    OUTPUT_FILE="${ALT:-$OUTPUT_FILE}"
fi

if [ ! -f "$OUTPUT_FILE" ]; then
    echo "No analysis file found"
    write_scored_result "0.0" "missing_expected_output"
    exit 0
fi

echo "Scoring: $OUTPUT_FILE"
VALIDATION_OUTPUT_PATH="$OUTPUT_FILE"

SCORE=$(python3 - "$OUTPUT_FILE" <<'PYEOF'
import sys, re

path = sys.argv[1]
try:
    content = open(path).read()
except Exception:
    print("0.0", end="")
    sys.exit(0)

score = 0.0

# Component 1: gap identification precision (0.40)
gap_sections = re.findall(r'Gap\s+\d+|###\s+Gap', content)
n_gaps = len(gap_sections)
has_file_refs = bool(re.search(r'source/common/http|conn_manager|filter_manager', content))
has_line_refs = bool(re.search(r'[Ll]ines?\s*[:~]\s*\d+|~\d{3}', content))

print(f"Gaps found: {n_gaps}", file=sys.stderr)

if n_gaps >= 5:
    score += 0.30
elif n_gaps >= 3:
    score += 0.20
elif n_gaps >= 1:
    score += 0.10

if has_file_refs:
    score += 0.06
if has_line_refs:
    score += 0.04

# Component 2: proposed test case feasibility (0.30)
test_proposal_patterns = [
    r'[Pp]roposed [Tt]est|[Tt]est [Cc]ase|[Tt]est [Nn]ame',
    r'TEST_F\s*\(|TEST\s*\(',
    r'EXPECT_|ASSERT_',
    r'[Ss]etup|[Aa]ssert|[Vv]erify',
]
prop_hits = sum(1 for p in test_proposal_patterns if re.search(p, content))
score += min(0.30, prop_hits * 0.08)
print(f"Test proposal hits: {prop_hits}/4", file=sys.stderr)

# Component 3: code reference accuracy (0.30)
ref_patterns = [
    r'conn_manager_impl',
    r'filter_manager|FilterManager',
    r'header_map|HeaderMap',
    r'HIGH|MEDIUM|LOW',
    r'[Ww]hy [Ii]t [Mm]atters|[Ii]mpact|[Rr]isk',
]
ref_hits = sum(1 for p in ref_patterns if re.search(p, content))
score += min(0.30, ref_hits * 0.06)
print(f"Reference hits: {ref_hits}/5", file=sys.stderr)

score = min(1.0, score)
print(f"Final score: {score:.2f}", file=sys.stderr)
print(f"{score:.2f}", end="")
PYEOF
)

write_scored_result "$SCORE"
echo "Score: $SCORE"
exit 0
