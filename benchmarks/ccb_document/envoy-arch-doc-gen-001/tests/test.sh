#!/bin/bash
# Reward: checklist (0.0-1.0) — weighted pattern matching against ground_truth.json
# Verifier for docgen architecture tasks: scores /workspace/documentation.md
# against ground-truth topics, file references, data flow, and extension points.
#
# Scoring weights (from ground_truth.json):
#   required_topics:   0.40
#   file_references:   0.25
#   data_flow:         0.20
#   extension_points:  0.15

set -e

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh


DOC="/workspace/documentation.md"
GROUND_TRUTH="/tests/ground_truth.json"
REWARD_FILE="/logs/verifier/reward.txt"

mkdir -p /logs/verifier

# ── Check prerequisites ────────────────────────────────────────────────
if [ ! -f "$GROUND_TRUTH" ]; then
    echo "ERROR: ground_truth.json not found at $GROUND_TRUTH"
    echo "0.0" > "$REWARD_FILE"
    exit 0
fi

if [ ! -f "$DOC" ]; then
    echo "No documentation found at $DOC"
    echo "Agent did not produce the required output."
    echo "0.0" > "$REWARD_FILE"
    exit 0
fi

DOC_SIZE=$(wc -c < "$DOC")
if [ "$DOC_SIZE" -lt 500 ]; then
    echo "Documentation is too short (${DOC_SIZE} bytes). Likely incomplete."
    echo "0.0" > "$REWARD_FILE"
    exit 0
fi

echo "Scoring architecture documentation ($DOC_SIZE bytes)..."
echo "Ground truth: $GROUND_TRUTH"
echo ""

# ── Delegate scoring to Python ────────────────────────────────────────
python3 << 'PYEOF'
import json, re, sys

DOC_PATH = "/workspace/documentation.md"
GT_PATH = "/tests/ground_truth.json"
REWARD_PATH = "/logs/verifier/reward.txt"

with open(DOC_PATH) as f:
    doc = f.read()
with open(GT_PATH) as f:
    gt = json.load(f)

def check_any_pattern(patterns, text):
    """Return True if at least one pattern matches (case-insensitive)."""
    for p in patterns:
        try:
            if re.search(p, text, re.IGNORECASE):
                return True
        except re.error:
            if p.lower() in text.lower():
                return True
    return False

def check_all_patterns(patterns, text):
    """Return True if ALL patterns match (each represents a step in the flow)."""
    for p in patterns:
        try:
            if not re.search(p, text, re.IGNORECASE):
                return False
        except re.error:
            if p.lower() not in text.lower():
                return False
    return True

# ── Score required_topics ──────────────────────────────────────────────
print("=== Required Topics ===")
t_score, t_total = 0.0, 0.0
for item in gt["required_topics"]:
    t_total += item["weight"]
    if check_any_pattern(item["patterns"], doc):
        t_score += item["weight"]
        print(f"  [x] {item['description']} (weight: {item['weight']})")
    else:
        print(f"  [ ] {item['description']} (weight: {item['weight']})")
t_ratio = t_score / t_total if t_total > 0 else 0
print(f"  Topics score: {t_score:.2f} / {t_total:.2f} = {t_ratio:.2f}")
print()

# ── Score file_references ──────────────────────────────────────────────
print("=== File References ===")
r_score, r_total = 0.0, 0.0
for item in gt["file_references"]:
    r_total += item["weight"]
    if check_any_pattern(item["patterns"], doc):
        r_score += item["weight"]
        print(f"  [x] {item['description']} (weight: {item['weight']})")
    else:
        print(f"  [ ] {item['description']} (weight: {item['weight']})")
r_ratio = r_score / r_total if r_total > 0 else 0
print(f"  File refs score: {r_score:.2f} / {r_total:.2f} = {r_ratio:.2f}")
print()

# ── Score data_flow ────────────────────────────────────────────────────
print("=== Data Flow ===")
d_score, d_total = 0.0, 0.0
for item in gt["data_flow"]:
    d_total += item["weight"]
    if check_all_patterns(item["patterns"], doc):
        d_score += item["weight"]
        print(f"  [x] {item['description']} (weight: {item['weight']})")
    else:
        print(f"  [ ] {item['description']} (weight: {item['weight']})")
d_ratio = d_score / d_total if d_total > 0 else 0
print(f"  Data flow score: {d_score:.2f} / {d_total:.2f} = {d_ratio:.2f}")
print()

# ── Score extension_points ─────────────────────────────────────────────
print("=== Extension Points ===")
e_score, e_total = 0.0, 0.0
for item in gt["extension_points"]:
    e_total += item["weight"]
    if check_any_pattern(item["patterns"], doc):
        e_score += item["weight"]
        print(f"  [x] {item['description']} (weight: {item['weight']})")
    else:
        print(f"  [ ] {item['description']} (weight: {item['weight']})")
e_ratio = e_score / e_total if e_total > 0 else 0
print(f"  Extension points score: {e_score:.2f} / {e_total:.2f} = {e_ratio:.2f}")
print()

# ── Compute weighted total ─────────────────────────────────────────────
w = gt["weights"]
total = (t_ratio * w["required_topics"] +
         r_ratio * w["file_references"] +
         d_ratio * w["data_flow"] +
         e_ratio * w["extension_points"])

print("=== Final Score ===")
print(f"  Topics:     {t_ratio:.2f} * {w['required_topics']} = {t_ratio * w['required_topics']:.3f}")
print(f"  File refs:  {r_ratio:.2f} * {w['file_references']} = {r_ratio * w['file_references']:.3f}")
print(f"  Data flow:  {d_ratio:.2f} * {w['data_flow']} = {d_ratio * w['data_flow']:.3f}")
print(f"  Extensions: {e_ratio:.2f} * {w['extension_points']} = {e_ratio * w['extension_points']:.3f}")
print(f"  TOTAL:      {total:.2f}")

with open(REWARD_PATH, "w") as f:
    f.write(f"{total:.2f}\n")

print()
print(f"Tests completed - Score: {total:.2f}")
PYEOF
