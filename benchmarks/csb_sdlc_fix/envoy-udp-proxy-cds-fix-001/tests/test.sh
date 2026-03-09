#!/bin/bash
# Reward: diff_similarity (0.0-1.0) — diff match to expected patch

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh
# Artifact mode: parse answer.json, extract analysis text, apply diffs
if [ -f /tmp/.artifact_only_mode ] && [ -f /tests/answer_json_verifier_lib.sh ]; then
    source /tests/answer_json_verifier_lib.sh
fi

set -eo pipefail
TASK_WORKDIR="${TASK_WORKDIR:-/workspace}"
TASK_REPO_ROOT="${TASK_REPO_ROOT:-${VERIFY_REPO:-$TASK_WORKDIR}}"
TASK_OUTPUT="${TASK_OUTPUT:-/workspace/answer.json}"
VERIFY_REPO="${VERIFY_REPO:-$TASK_REPO_ROOT}"
ARTIFACT_REQUIRED=false
if [ "${ARTIFACT_ONLY:-false}" = "true" ]; then
    ARTIFACT_REQUIRED=true
fi

mkdir -p /logs/verifier
cd "$TASK_REPO_ROOT"
git config --global --add safe.directory "$TASK_REPO_ROOT" 2>/dev/null || true

write_invalid_output() {
    local code="$1"
    local message="$2"
    python3 - "$code" "$message" "$TASK_OUTPUT" "$ARTIFACT_REQUIRED" <<'PYEOF'
import json
import sys

code, message, primary_path, required_artifact = sys.argv[1:5]
required = required_artifact == "true"
reward_payload = {
    "reward": 0.0,
    "gate": code,
    "error": message,
}
validation_payload = {
    "schema_version": "validation_result.v1alpha1",
    "status": "invalid_output",
    "scorable": False,
    "scorer_family": "diff_similarity",
    "reward": 0.0,
    "pass_threshold": 0.5,
    "passed": False,
    "output_contract": {
        "mode": "answer_json_bridge",
        "primary_path": primary_path,
        "required_artifact": required,
    },
    "sub_scores": {},
    "failure": {
        "code": code,
        "message": message,
        "stage": "output_validation",
    },
    "legacy": {
        "reward_json": reward_payload,
    },
}
with open("/logs/verifier/reward.json", "w") as f:
    json.dump(reward_payload, f, indent=2)
with open("/logs/verifier/validation_result.json", "w") as f:
    json.dump(validation_payload, f, indent=2)
with open("/logs/verifier/reward.txt", "w") as f:
    f.write("0.0")
PYEOF
}

write_validation_from_reward_json() {
    local fallback_status="$1"
    python3 - "$fallback_status" "$TASK_OUTPUT" "$ARTIFACT_REQUIRED" <<'PYEOF'
import json
import os
import sys

fallback_status, primary_path, required_artifact = sys.argv[1:4]
required = required_artifact == "true"
status = fallback_status
reward_payload = {}
reward_json_path = "/logs/verifier/reward.json"

if os.path.isfile(reward_json_path):
    try:
        with open(reward_json_path) as f:
            reward_payload = json.load(f)
    except Exception as exc:
        status = "verifier_error"
        reward_payload = {"reward": 0.0, "error": f"Failed to parse reward.json: {exc}"}
else:
    status = "verifier_error"
    reward_payload = {"reward": 0.0, "error": "reward.json not written by verifier"}

reward = reward_payload.get("reward", 0.0)
try:
    reward = float(reward)
except (TypeError, ValueError):
    reward = 0.0
    status = "verifier_error"

if reward_payload.get("error"):
    status = "verifier_error"

sub_scores = {}
for key in ("file_recall", "line_recall", "line_precision"):
    value = reward_payload.get(key)
    if isinstance(value, (int, float)):
        sub_scores[key] = float(value)

details = {}
for key in ("expected_files", "actual_files", "expected_lines_total", "actual_lines_total", "gate", "error"):
    value = reward_payload.get(key)
    if value is not None:
        details[key] = value

failure = None
passed = False
if status == "scored":
    passed = reward >= 0.5
else:
    failure = {
        "code": "verifier_exception" if reward_payload.get("error") else "missing_reward_json",
        "message": str(reward_payload.get("error") or "Verifier did not produce a usable reward payload"),
        "stage": "scoring",
    }

payload = {
    "schema_version": "validation_result.v1alpha1",
    "status": status,
    "scorable": status == "scored",
    "scorer_family": "diff_similarity",
    "reward": reward,
    "pass_threshold": 0.5,
    "passed": passed,
    "output_contract": {
        "mode": "answer_json_bridge",
        "primary_path": primary_path,
        "required_artifact": required,
    },
    "sub_scores": sub_scores,
    "failure": failure,
    "legacy": {
        "reward_json": reward_payload,
    },
}
if details:
    payload["details"] = details

with open("/logs/verifier/validation_result.json", "w") as f:
    json.dump(payload, f, indent=2)
PYEOF
}

if [ "${ARTIFACT_ONLY:-false}" = "true" ] && {
    [ "${ANSWER_JSON_MISSING:-false}" = "true" ] || [ "${ANSWER_JSON_NO_CHANGES:-false}" = "true" ];
}; then
    write_invalid_output "missing_required_output" \
        "answer.json missing or has no usable artifact payload at $TASK_OUTPUT"
    exit 0
fi

# Resolve initial commit — mirrors use orphan commits with different SHAs than upstream
PRE_FIX_REV=$(git rev-parse HEAD 2>/dev/null || echo "HEAD")
python3 /tests/verify_diff.py \
    --expected /tests/expected.diff \
    --pre-fix-rev "$PRE_FIX_REV" \
    --output /logs/verifier/reward.json \
    2>&1 | tee /logs/verifier/verifier.log
REWARD=$(python3 -c "import json; print(json.load(open('/logs/verifier/reward.json')).get('reward', 0.0))" 2>/dev/null || echo "0.0")
echo "$REWARD" > /logs/verifier/reward.txt
write_validation_from_reward_json "scored"
echo "Final reward: $REWARD"
git diff "$PRE_FIX_REV" > /logs/verifier/agent.diff 2>/dev/null || true
git diff "$PRE_FIX_REV" --stat > /logs/verifier/diff.stat 2>/dev/null || true
exit 0
