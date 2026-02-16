#!/bin/bash
# Reward: F1 (0.0-1.0) — precision/recall scoring of structured JSON output
#
# crossrepo-sym-001: Find all callers of StreamAggregatedResources across
# envoyproxy/envoy and grpc/grpc-go. Agent outputs /workspace/callers.json,
# scored against ground_truth.json on composite key (repo, file, function).

set -e

OUTPUT_PATH="/workspace/callers.json"
GROUND_TRUTH="/tests/ground_truth.json"
REWARD_FILE="/logs/verifier/reward.txt"

mkdir -p /logs/verifier

# ── Check prerequisites ───────────────────────────────────────────────────
if [ ! -f "$GROUND_TRUTH" ]; then
    echo "ERROR: ground_truth.json not found at $GROUND_TRUTH"
    echo "0.0" > "$REWARD_FILE"
    exit 0
fi

if [ ! -f "$OUTPUT_PATH" ]; then
    echo "No agent output found at $OUTPUT_PATH"
    echo "Agent did not produce the required output."
    echo "0.0" > "$REWARD_FILE"
    exit 0
fi

echo "Scoring agent output..."
echo "Output: $OUTPUT_PATH"
echo "Ground truth: $GROUND_TRUTH"
echo ""

# ── Delegate scoring to Python ────────────────────────────────────────────
OUTPUT_PATH="$OUTPUT_PATH" GROUND_TRUTH="$GROUND_TRUTH" REWARD_FILE="$REWARD_FILE" \
python3 << 'PYEOF'
import json, os, re, sys

OUTPUT_PATH = os.environ["OUTPUT_PATH"]
GT_PATH = os.environ["GROUND_TRUTH"]
REWARD_PATH = os.environ["REWARD_FILE"]

def write_reward(score):
    """Write score to reward file and print summary."""
    with open(REWARD_PATH, "w") as f:
        f.write(f"{score:.2f}\n")
    print(f"\nTests completed - Score: {score:.2f}")

def strip_code_fences(text):
    """Strip markdown code fences if agent wrapped JSON in ```json blocks."""
    m = re.search(r'```(?:json)?\s*\n(.*?)```', text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()

# ── Load ground truth ────────────────────────────────────────────────────
with open(GT_PATH) as f:
    gt = json.load(f)

key_fields = gt.get("key_fields", [])
expected = gt.get("entries", [])

if not key_fields:
    print("ERROR: ground_truth.json must specify 'key_fields' (list of field names)")
    write_reward(0.0)
    sys.exit(0)

if not expected:
    print("ERROR: ground_truth.json has no entries")
    write_reward(0.0)
    sys.exit(0)

num_expected = len(expected)

# ── Load agent output ────────────────────────────────────────────────────
try:
    with open(OUTPUT_PATH) as f:
        raw = f.read()
    raw = strip_code_fences(raw)
    reported = json.loads(raw)
    if not isinstance(reported, list):
        print("Agent output is not a JSON array — scoring as empty.")
        reported = []
except (json.JSONDecodeError, ValueError) as e:
    print(f"Malformed JSON in agent output: {e}")
    reported = []

num_reported = len(reported)

if num_reported == 0:
    print("Agent output is empty — no entries to score.")
    print(f"Expected {num_expected} entries.")
    write_reward(0.0)
    sys.exit(0)

# ── Build composite keys ─────────────────────────────────────────────────
def make_key(entry, fields):
    """Build a composite key tuple from an entry's field values."""
    return tuple(str(entry.get(f, "")).strip() for f in fields)

expected_keys = [make_key(e, key_fields) for e in expected]
reported_keys = [make_key(r, key_fields) for r in reported]

# ── Match reported against expected (one match per expected entry) ────────
matched_expected = set()
true_positives = 0

for r_idx, r_key in enumerate(reported_keys):
    for e_idx, e_key in enumerate(expected_keys):
        if e_idx in matched_expected:
            continue
        if r_key == e_key:
            matched_expected.add(e_idx)
            true_positives += 1
            break

# ── Compute metrics ──────────────────────────────────────────────────────
precision = true_positives / num_reported if num_reported > 0 else 0.0
recall = true_positives / num_expected if num_expected > 0 else 0.0

if precision + recall > 0:
    f1 = 2 * precision * recall / (precision + recall)
else:
    f1 = 0.0

# ── Print detailed results ───────────────────────────────────────────────
print("=== F1 Scoring ===")
print(f"  Key fields:      {key_fields}")
print(f"  Expected entries: {num_expected}")
print(f"  Reported entries: {num_reported}")
print(f"  True positives:   {true_positives}")
print(f"  False positives:  {num_reported - true_positives}")
print(f"  False negatives:  {num_expected - true_positives}")
print()
print(f"  Precision: {precision:.3f}")
print(f"  Recall:    {recall:.3f}")
print(f"  F1:        {f1:.3f}")

# ── Show matched and missed entries ──────────────────────────────────────
if true_positives > 0:
    print(f"\n=== Matched ({true_positives}) ===")
    for e_idx in sorted(matched_expected):
        print(f"  [x] {dict(zip(key_fields, expected_keys[e_idx]))}")

missed = [i for i in range(num_expected) if i not in matched_expected]
if missed:
    print(f"\n=== Missed ({len(missed)}) ===")
    for e_idx in missed:
        print(f"  [ ] {dict(zip(key_fields, expected_keys[e_idx]))}")

write_reward(f1)
PYEOF
