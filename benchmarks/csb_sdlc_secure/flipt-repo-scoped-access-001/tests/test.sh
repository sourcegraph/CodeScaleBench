#!/bin/bash
# Reward: checklist (0.0-1.0) — weighted correctness checks
# Verifies evaluation metrics feature in flipt internal/server/evaluation/

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


cd "$TASK_REPO_ROOT"

mkdir -p /logs/verifier

git config --global --add safe.directory "$TASK_REPO_ROOT" 2>/dev/null || true

if [ "${ARTIFACT_ONLY:-false}" = "true" ] && [ ! -f "${ANSWER_JSON:-$TASK_OUTPUT}" ]; then
    write_invalid_output "missing_required_output" \
        "answer.json not found at ${ANSWER_JSON:-$TASK_OUTPUT}"
    exit 0
fi


# Guard: check for code changes
UNSTAGED_COUNT=$(git diff --stat 2>/dev/null | wc -l)
STAGED_COUNT=$(git diff --cached --stat 2>/dev/null | wc -l)
UNTRACKED_COUNT=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l)
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
fi
echo "Change detection: unstaged=$UNSTAGED_COUNT staged=$STAGED_COUNT untracked=$UNTRACKED_COUNT commits=$COMMIT_COUNT"
if [ "$UNSTAGED_COUNT" -eq 0 ] && [ "$STAGED_COUNT" -eq 0 ] && [ "$UNTRACKED_COUNT" -eq 0 ] && [ "$COMMIT_COUNT" -eq 0 ]; then
    echo "No code changes detected"
    write_scored_result "0.0" "no_code_changes"
    exit 0
fi

echo "Running governance task 2 verification..."

SCORE_NUMERATOR=0

# Check 1 (0.25): metrics.go file exists with EvaluationMetrics struct
if [ -f "internal/server/evaluation/metrics.go" ]; then
    if grep -q "EvaluationMetrics" internal/server/evaluation/metrics.go; then
        echo "[x] metrics.go exists with EvaluationMetrics struct"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
    else
        echo "[~] metrics.go exists but missing EvaluationMetrics struct"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 10))
    fi
else
    echo "[ ] metrics.go not found"
fi

# Check 2 (0.25): Concurrent safety (sync.Mutex or sync.RWMutex)
if [ -f "internal/server/evaluation/metrics.go" ]; then
    if grep -qE "sync\.(RW)?Mutex" internal/server/evaluation/metrics.go; then
        echo "[x] Concurrent-safe implementation found"
        SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
    else
        echo "[ ] No mutex found in metrics.go"
    fi
else
    echo "[ ] Cannot check concurrency (no metrics.go)"
fi

# Check 3 (0.25): Server struct integration (metrics field added to server.go)
if git diff --unified=0 "$ORIGIN_REF..HEAD" -- internal/server/evaluation/server.go 2>/dev/null | grep -qi "metrics"; then
    echo "[x] Server struct modified with metrics integration"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
elif git diff --unified=0 -- internal/server/evaluation/server.go 2>/dev/null | grep -qi "metrics"; then
    echo "[x] Server struct modified with metrics integration (unstaged)"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
else
    echo "[ ] Server struct not modified with metrics"
fi

# Check 4 (0.25): Go compilation succeeds
echo "Running Go compilation check..."
# Disable go.work to avoid version mismatches when sg_only verifier restores the
# full repo (its go.work may require a newer Go than the container provides).
if GOWORK=off go build ./internal/server/evaluation/... 2>/logs/verifier/build_errors.txt; then
    echo "[x] Go compilation passed"
    SCORE_NUMERATOR=$((SCORE_NUMERATOR + 25))
else
    echo "[ ] Go compilation failed"
fi

# Bonus penalty: check changes are scoped to evaluation package
ALL_CHANGED=""
if [ -n "$ORIGIN_REF" ]; then
    ALL_CHANGED=$(git diff --name-only "$ORIGIN_REF..HEAD" 2>/dev/null)
fi
ALL_CHANGED="$ALL_CHANGED
$(git diff --name-only 2>/dev/null)
$(git diff --cached --name-only 2>/dev/null)
$(git ls-files --others --exclude-standard 2>/dev/null)"
ALL_CHANGED=$(echo "$ALL_CHANGED" | sort -u | grep -v '^$' || true)

OUTSIDE_SCOPE=0
if [ -n "$ALL_CHANGED" ]; then
    while IFS= read -r f; do
        case "$f" in
            internal/server/evaluation/*) ;;
            *) OUTSIDE_SCOPE=1; echo "WARNING: change outside evaluation/: $f" ;;
        esac
    done <<< "$ALL_CHANGED"
fi
if [ "$OUTSIDE_SCOPE" -eq 0 ]; then
    echo "[x] All changes within internal/server/evaluation/"
else
    echo "[!] Changes outside evaluation/ — governance concern"
fi

SCORE=$(awk "BEGIN {printf \"%.2f\", $SCORE_NUMERATOR / 100}")
write_scored_result "$SCORE"
echo ""
echo "[x] Tests completed - Score: $SCORE"
