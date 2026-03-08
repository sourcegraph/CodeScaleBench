#!/bin/bash
# Reward: checklist (0.0-1.0) — integration test quality score
set -euo pipefail

[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh
# Artifact mode: parse answer.json, extract analysis text, apply diffs
if [ -f /tmp/.artifact_only_mode ] && [ -f /tests/answer_json_verifier_lib.sh ]; then
    source /tests/answer_json_verifier_lib.sh
fi

mkdir -p /logs/verifier

TARGET_FILE="/workspace/integration/evaluation_integration_test.go"
ALT_FILE=$(find /workspace -name "*integration*test*.go" -o -name "*test*integration*.go" 2>/dev/null | head -1)
TEST_FILE="${ALT_FILE:-$TARGET_FILE}"

if [ ! -f "$TEST_FILE" ]; then
    echo "No integration test file found"
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

SCORE=$(python3 - "$TEST_FILE" <<'PYEOF'
import sys, re

path = sys.argv[1]
content = open(path).read()
score = 0.0

# Component 1: file presence (0.20)
score += 0.20

# Component 2: API endpoint coverage (0.40)
api_patterns = [
    r'boolean|Boolean',
    r'variant|Variant',
    r'batch|Batch',
    r'namespace|Namespace',
    r'evaluate|Evaluate',
    r'/evaluate|/v1/',
]
api_hits = sum(1 for p in api_patterns if re.search(p, content))
score += min(0.40, api_hits * 0.08)
print(f"API coverage hits: {api_hits}/6", file=sys.stderr)

# Component 3: error case handling (0.25)
error_patterns = [
    r'404|NotFound|not.found',
    r'400|BadRequest|invalid',
    r'error|Error|err\b',
    r't\.(Fatal|Error|Errorf)',
]
err_hits = sum(1 for p in error_patterns if re.search(p, content))
score += min(0.25, err_hits * 0.07)
print(f"Error case hits: {err_hits}/4", file=sys.stderr)

# Component 4: test structure (0.15)
test_funcs = re.findall(r'func\s+(Test\w+)\s*\(', content)
n = len(test_funcs)
print(f"Test functions: {test_funcs}", file=sys.stderr)
if n >= 6:
    score += 0.15
elif n >= 3:
    score += 0.10
elif n >= 1:
    score += 0.05

print(f"Final score: {score:.2f}", file=sys.stderr)
print(f"{score:.2f}", end="")
PYEOF
)

echo "$SCORE" > /logs/verifier/reward.txt
echo "Score: $SCORE"
exit 0
