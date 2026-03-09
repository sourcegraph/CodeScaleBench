#!/bin/bash

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

set -eo pipefail
# RepoQA SR-QA Verification Script

# SR-QA tasks: verifier only does JSON string matching (function name + path).
# sgonly_verifier_wrapper clone is NOT needed — skipped to avoid 39+ min
# Firefox mirror clone that causes VerifierTimeoutError on MCP runs.

echo "Starting RepoQA verifier..." 1>&2
TASK_WORKDIR="${TASK_WORKDIR:-/app}"
TASK_REPO_ROOT="${TASK_REPO_ROOT:-$TASK_WORKDIR}"
TASK_OUTPUT="${TASK_OUTPUT:-$TASK_WORKDIR/solution.json}"
cd "$TASK_REPO_ROOT" || { echo "ERROR: Cannot cd to $TASK_REPO_ROOT"; exit 1; }
mkdir -p /logs/verifier

write_validation_failure() {
    local status="$1"
    local code="$2"
    local message="$3"
    local stage="$4"
    local primary_path="$5"
    python3 - "$status" "$code" "$message" "$stage" "$primary_path" <<'PYEOF'
import json
import sys

status, code, message, stage, primary_path = sys.argv[1:6]
payload = {
    "schema_version": "validation_result.v1alpha1",
    "status": status,
    "scorable": False,
    "scorer_family": "semantic_retrieval_qa",
    "reward": 0.0,
    "pass_threshold": 1.0,
    "passed": False,
    "output_contract": {
        "mode": "solution_json",
        "primary_path": primary_path,
        "required_artifact": True,
    },
    "sub_scores": {},
    "failure": {
        "code": code,
        "message": message,
        "stage": stage,
    },
}
with open("/logs/verifier/validation_result.json", "w") as f:
    json.dump(payload, f, indent=2)
PYEOF
}

if [ ! -f /tests/ground_truth.json ]; then
    echo "ERROR: No ground_truth.json found at /tests/ground_truth.json"
    echo '{"score": 0.0}' > /logs/verifier/reward.json
    echo "0.0" > /logs/verifier/reward.txt
    write_validation_failure "verifier_error" "missing_ground_truth" \
        "ground_truth.json not found at /tests/ground_truth.json" "verifier_runtime" "$TASK_OUTPUT"
    exit 0
fi

SOLUTION_FILE="$TASK_OUTPUT"
if [ ! -f "$SOLUTION_FILE" ]; then
    echo "ERROR: Agent did not create solution.json in /app/"
    echo '{"score": 0.0}' > /logs/verifier/reward.json
    echo "0.0" > /logs/verifier/reward.txt
    write_validation_failure "invalid_output" "missing_required_output" \
        "solution.json not found at $TASK_OUTPUT" "output_validation" "$TASK_OUTPUT"
    exit 0
fi

VERIFY_SCRIPT="$(mktemp /logs/verifier/verify_XXXXXX.py)"
cat > "$VERIFY_SCRIPT" << 'PYEOF'
import json, os, sys, re, traceback
sys.path.insert(0, "/tests")
from verifiers import SemanticRetrievalQAVerifier

try:
    with open("/tests/ground_truth.json") as f:
        ground_truth = json.load(f)
    with open(os.environ.get("TASK_OUTPUT", "/app/solution.json")) as f:
        raw = f.read()
    matches = re.findall(r"```(?:json)?\s*\n(.*?)```", raw, re.DOTALL)
    if matches:
        raw = matches[-1].strip()
    agent_output = json.loads(raw)

    verifier = SemanticRetrievalQAVerifier(ground_truth)
    result = verifier.verify(agent_output)
    score = float(result.correct_function)
    reward = {"score": score}
    validation_result = {
        "schema_version": "validation_result.v1alpha1",
        "status": "scored",
        "scorable": True,
        "scorer_family": "semantic_retrieval_qa",
        "reward": score,
        "pass_threshold": 1.0,
        "passed": score >= 1.0,
        "output_contract": {
            "mode": "solution_json",
            "primary_path": os.environ.get("TASK_OUTPUT", "/app/solution.json"),
            "required_artifact": True,
        },
        "sub_scores": {
            "correct_function": float(result.correct_function),
            "correct_path": float(result.correct_path),
            "justification_score": float(result.justification_score),
        },
        "failure": None,
        "details": {
            "reasoning": result.reasoning,
        },
        "legacy": {
            "reward_json": reward,
        },
    }

    print(f"Correct Function: {result.correct_function:.2f}")
    print(f"Correct Path: {result.correct_path:.2f}")
    print(f"Justification: {result.justification_score:.2f}")
    print(f"Details: {result.reasoning}")

    with open("/logs/verifier/reward.json", "w") as f:
        json.dump(reward, f, indent=2)
    with open("/logs/verifier/validation_result.json", "w") as f:
        json.dump(validation_result, f, indent=2)
    with open("/logs/verifier/reward.txt", "w") as f:
        f.write(str(reward["score"]))
except Exception as e:
    print(f"ERROR: {e}")
    traceback.print_exc()
    validation_result = {
        "schema_version": "validation_result.v1alpha1",
        "status": "verifier_error",
        "scorable": False,
        "scorer_family": "semantic_retrieval_qa",
        "reward": 0.0,
        "pass_threshold": 1.0,
        "passed": False,
        "output_contract": {
            "mode": "solution_json",
            "primary_path": os.environ.get("TASK_OUTPUT", "/app/solution.json"),
            "required_artifact": True,
        },
        "sub_scores": {},
        "failure": {
            "code": "verifier_exception",
            "message": str(e),
            "stage": "scoring",
        },
        "details": {
            "traceback": traceback.format_exc(),
        },
        "legacy": {
            "reward_json": {"score": 0.0},
        },
    }
    with open("/logs/verifier/reward.json", "w") as f:
        json.dump({"score": 0.0}, f)
    with open("/logs/verifier/validation_result.json", "w") as f:
        json.dump(validation_result, f, indent=2)
    with open("/logs/verifier/reward.txt", "w") as f:
        f.write("0.0")
PYEOF

python3 "$VERIFY_SCRIPT" 2>&1 | tee /logs/verifier/verify-debug.log
rm -f "$VERIFY_SCRIPT"
exit 0
