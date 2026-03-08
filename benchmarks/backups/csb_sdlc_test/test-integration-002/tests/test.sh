#!/bin/bash
# Reward: checklist (0.0-1.0) — media scanner integration test quality score
set -euo pipefail

[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh
# Artifact mode: parse answer.json, extract analysis text, apply diffs
if [ -f /tmp/.artifact_only_mode ] && [ -f /tests/answer_json_verifier_lib.sh ]; then
    source /tests/answer_json_verifier_lib.sh
fi

mkdir -p /logs/verifier

TARGET_FILE="/workspace/scanner/scanner_integration_test.go"
ALT_FILE=$(find /workspace -name "*scanner*test*.go" -o -name "*integration*scanner*.go" 2>/dev/null | head -1)
TEST_FILE="${ALT_FILE:-$TARGET_FILE}"

if [ ! -f "$TEST_FILE" ]; then
    echo "No test file found"
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

echo "Scoring test file: $TEST_FILE"

SCORE=$(python3 - "$TEST_FILE" <<'PYEOF'
import sys, re

path = sys.argv[1]
try:
    content = open(path).read()
except Exception:
    print("0.0", end="")
    sys.exit(0)

score = 0.0

# Component 1: file presence (0.20)
score += 0.20

# Component 2: pipeline stage coverage (0.40)
pipeline_patterns = [
    r'metadata|Metadata|tag|Tag',
    r'album|Album',
    r'artist|Artist',
    r'track|Track',
    r'scan|Scan',
    r'database|DB|store|Store|persist',
    r'file|File|directory|Directory',
]
hits = sum(1 for p in pipeline_patterns if re.search(p, content))
score += min(0.40, hits * 0.06)
print(f"Pipeline stage hits: {hits}/7", file=sys.stderr)

# Component 3: fixture usage (0.25)
fixture_patterns = [
    r'fixture|Fixture|testdata|TestData|t\.TempDir|os\.MkdirTemp',
    r'mock|Mock|fake|Fake',
    r'setUp|SetUp|helper|Helper',
]
fix_hits = sum(1 for p in fixture_patterns if re.search(p, content))
score += min(0.25, fix_hits * 0.09)
print(f"Fixture hits: {fix_hits}/3", file=sys.stderr)

# Component 4: test function count (0.15)
test_funcs = re.findall(r'func\s+(Test\w+)\s*\(', content)
n = len(test_funcs)
print(f"Test functions: {n}", file=sys.stderr)
if n >= 5:
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
