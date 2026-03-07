#!/bin/bash
# test.sh — Deterministic SDLC verifier for CCX-platform-091
# Promoted from csb_org_platform -> csb_sdlc_test
#
# Reward: suite-weighted composite (0.0-1.0) via oracle file/symbol/chain/keyword F1
# Multiple assertion patterns: file_set_match + symbol_resolution + keyword_presence
#   [+ dependency_chain where oracle defines chains]
#
# Scoring weights (csb_sdlc_test):
#   See promoted_verifier.py SUITE_WEIGHTS for per-check weight allocation.

# sg_only mode guard: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

# NOTE: set -e intentionally NOT used — fallback logic requires graceful failure handling
set -uo pipefail

TASK_ID="CCX-platform-091"
TARGET_SUITE="csb_sdlc_test"
ANSWER_PATH="/workspace/answer.json"
TASK_SPEC_PATH="/tests/task_spec.json"
PROMOTED_VERIFIER="/tests/promoted_verifier.py"
ORACLE_CHECKS="/tests/oracle_checks.py"
REWARD_PATH="/logs/verifier/reward.txt"
VALIDATION_RESULT="/logs/verifier/validation_result.json"

mkdir -p /logs/verifier

echo "=== $TASK_ID deterministic verifier ===" >&2
echo "Suite: $TARGET_SUITE (promoted from csb_org_platform)" >&2
echo "" >&2

# ------------------------------------------------------------------
# Assertion 1: answer.json exists
# ------------------------------------------------------------------
if [ ! -f "$ANSWER_PATH" ]; then
    echo "FAIL: answer.json not found at $ANSWER_PATH" >&2
    echo "0.0" > "$REWARD_PATH"
    echo '{"composite_score": 0.0, "error": "answer.json not found"}' > "$VALIDATION_RESULT"
    exit 1
fi
echo "PASS: answer.json exists" >&2

# ------------------------------------------------------------------
# Assertion 2: answer.json is valid JSON with expected structure
# ------------------------------------------------------------------
STRUCT_CHECK=$(python3 << 'PYEOF'
import json, sys
try:
    with open("/workspace/answer.json") as f:
        data = json.load(f)
except (json.JSONDecodeError, OSError) as e:
    print(f"invalid JSON: {e}", file=sys.stderr)
    sys.exit(1)
if not isinstance(data, dict):
    print("answer.json is not a JSON object", file=sys.stderr)
    sys.exit(1)
keys = set(data.keys())
expected = {"files", "symbols", "text", "chain", "dependency_chain", "answer"}
if not keys & expected:
    print(f"answer.json missing expected keys (has: {keys})", file=sys.stderr)
    sys.exit(1)
print("ok")
PYEOF
) 2>&1

if [ "$STRUCT_CHECK" != "ok" ]; then
    echo "FAIL: answer.json structure check: $STRUCT_CHECK" >&2
    echo "0.0" > "$REWARD_PATH"
    echo '{"composite_score": 0.0, "error": "answer.json invalid structure"}' > "$VALIDATION_RESULT"
    exit 1
fi
echo "PASS: answer.json is valid JSON with expected structure" >&2

# ------------------------------------------------------------------
# Assertion 3: oracle data available
# ------------------------------------------------------------------
if [ ! -f "$TASK_SPEC_PATH" ]; then
    echo "FAIL: task_spec.json not found" >&2
    echo "0.0" > "$REWARD_PATH"
    exit 1
fi
if [ ! -f "$ORACLE_CHECKS" ]; then
    echo "FAIL: oracle_checks.py not found" >&2
    echo "0.0" > "$REWARD_PATH"
    exit 1
fi
echo "PASS: oracle data and checker available" >&2

# ------------------------------------------------------------------
# Assertion 4+: Run suite-weighted oracle checks
# ------------------------------------------------------------------
echo "" >&2
echo "Running suite-weighted oracle checks ($TARGET_SUITE)..." >&2

if [ -f "$PROMOTED_VERIFIER" ]; then
    # Use promoted_verifier.py for suite-specific weights
    SCORE=$(python3 "$PROMOTED_VERIFIER" \
        --answer "$ANSWER_PATH" \
        --spec "$TASK_SPEC_PATH" \
        --suite "$TARGET_SUITE" \
        --output "$VALIDATION_RESULT" \
        --verbose 2>&1 | tee /dev/stderr | tail -1) || true
else
    # Fallback: use oracle_checks.py directly (equal weights)
    echo "WARNING: promoted_verifier.py not found, using oracle_checks.py directly" >&2
    SCORE=$(python3 "$ORACLE_CHECKS" \
        --answer "$ANSWER_PATH" \
        --spec "$TASK_SPEC_PATH" \
        --verbose 2>&1 | tee /dev/stderr | tail -1) || true
fi

# ------------------------------------------------------------------
# Validate and write reward
# ------------------------------------------------------------------
if ! echo "$SCORE" | python3 -c "import sys; float(sys.stdin.read().strip())" 2>/dev/null; then
    echo "FAIL: verifier did not return a valid score: $SCORE" >&2
    echo "0.0" > "$REWARD_PATH"
    exit 1
fi

echo "" >&2
echo "Composite score: $SCORE" >&2
echo "$SCORE" > "$REWARD_PATH"

# ------------------------------------------------------------------
# Per-check assertion summary (if validation_result.json exists)
# ------------------------------------------------------------------
if [ -f "$VALIDATION_RESULT" ]; then
    python3 << 'PYEOF2' >&2 || true
import json, sys
result = json.load(open("/logs/verifier/validation_result.json"))
per_check = result.get("per_check", {})
print("")
print("Per-check assertions:")
for check_type, info in per_check.items():
    score = info.get("score", 0)
    weight = info.get("weight", 0)
    status = "PASS" if score > 0 else "FAIL"
    print(f"  {status}: {check_type} = {score:.4f} (weight={weight:.2f})")
PYEOF2
fi

echo "" >&2
echo "Reward: $SCORE" >&2

# Exit-code-first (SWE-Factory pattern)
python3 -c "import sys; sys.exit(0 if float('$SCORE') > 0 else 1)"
