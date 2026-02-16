#!/bin/bash
# Reward: checklist (0.0-1.0) — weighted pattern matching against ground_truth.json
# Verifier for investigation tasks: scores /logs/agent/investigation.md
# against ground-truth findings, file references, causal chains, and negative checks.
#
# Scoring weights (from ground_truth.json):
#   required_findings: 0.40
#   file_references:   0.30
#   causal_chain:      0.20
#   negative_checks:   0.10

set -e

REPORT="/logs/agent/investigation.md"
GROUND_TRUTH="/tests/ground_truth.json"
REWARD_FILE="/logs/verifier/reward.txt"

mkdir -p /logs/verifier

# ── Check prerequisites ────────────────────────────────────────────────
if [ ! -f "$GROUND_TRUTH" ]; then
    echo "ERROR: ground_truth.json not found at $GROUND_TRUTH"
    echo "0.0" > "$REWARD_FILE"
    exit 0
fi

if [ ! -f "$REPORT" ]; then
    echo "No investigation report found at $REPORT"
    echo "Agent did not produce the required output."
    echo "0.0" > "$REWARD_FILE"
    exit 0
fi

REPORT_SIZE=$(wc -c < "$REPORT")
if [ "$REPORT_SIZE" -lt 100 ]; then
    echo "Investigation report is too short (${REPORT_SIZE} bytes). Likely incomplete."
    echo "0.0" > "$REWARD_FILE"
    exit 0
fi

echo "Scoring investigation report ($REPORT_SIZE bytes)..."
echo "Ground truth: $GROUND_TRUTH"
echo ""

# ── Delegate scoring to Python (avoids shell escaping issues with regex) ─
python3 << 'PYEOF'
import json, re, sys

REPORT_PATH = "/logs/agent/investigation.md"
GT_PATH = "/tests/ground_truth.json"
REWARD_PATH = "/logs/verifier/reward.txt"

with open(REPORT_PATH) as f:
    report = f.read()
with open(GT_PATH) as f:
    gt = json.load(f)

def check_any_pattern(patterns, text):
    """Return True if at least one pattern matches (case-insensitive)."""
    for p in patterns:
        try:
            if re.search(p, text, re.IGNORECASE):
                return True
        except re.error:
            # Fall back to literal substring match if regex is invalid
            if p.lower() in text.lower():
                return True
    return False

def check_all_patterns(patterns, text):
    """Return True if ALL patterns match (each represents a step in causal chain)."""
    for p in patterns:
        try:
            if not re.search(p, text, re.IGNORECASE):
                return False
        except re.error:
            if p.lower() not in text.lower():
                return False
    return True

# ── Score required_findings ──────────────────────────────────────────────
print("=== Required Findings ===")
f_score, f_total = 0.0, 0.0
for item in gt["required_findings"]:
    f_total += item["weight"]
    if check_any_pattern(item["patterns"], report):
        f_score += item["weight"]
        print(f"  [x] {item['description']} (weight: {item['weight']})")
    else:
        print(f"  [ ] {item['description']} (weight: {item['weight']})")
f_ratio = f_score / f_total if f_total > 0 else 0
print(f"  Findings score: {f_score:.2f} / {f_total:.2f} = {f_ratio:.2f}")
print()

# ── Score file_references ────────────────────────────────────────────────
print("=== File References ===")
r_score, r_total = 0.0, 0.0
for item in gt["file_references"]:
    r_total += item["weight"]
    if check_any_pattern(item["patterns"], report):
        r_score += item["weight"]
        print(f"  [x] {item['description']} (weight: {item['weight']})")
    else:
        print(f"  [ ] {item['description']} (weight: {item['weight']})")
r_ratio = r_score / r_total if r_total > 0 else 0
print(f"  File refs score: {r_score:.2f} / {r_total:.2f} = {r_ratio:.2f}")
print()

# ── Score causal_chain ───────────────────────────────────────────────────
print("=== Causal Chain ===")
c_score, c_total = 0.0, 0.0
for item in gt["causal_chain"]:
    c_total += item["weight"]
    # All patterns must match (they represent steps in the causal chain)
    if check_all_patterns(item["patterns"], report):
        c_score += item["weight"]
        print(f"  [x] {item['description']} (weight: {item['weight']})")
    else:
        print(f"  [ ] {item['description']} (weight: {item['weight']})")
c_ratio = c_score / c_total if c_total > 0 else 0
print(f"  Causal chain score: {c_score:.2f} / {c_total:.2f} = {c_ratio:.2f}")
print()

# ── Score negative_checks ────────────────────────────────────────────────
print("=== Negative Checks ===")
n_score, n_total = 0.0, 0.0
for item in gt["negative_checks"]:
    n_total += item["weight"]
    # Negative checks PASS when the pattern is NOT found
    if not check_any_pattern(item["patterns"], report):
        n_score += item["weight"]
        print(f"  [x] {item['description']} (weight: {item['weight']})")
    else:
        print(f"  [ ] FAIL: {item['description']} (weight: {item['weight']}) -- wrong conclusion found")
n_ratio = n_score / n_total if n_total > 0 else 1.0
print(f"  Negative checks score: {n_score:.2f} / {n_total:.2f} = {n_ratio:.2f}")
print()

# ── Compute weighted total ───────────────────────────────────────────────
w = gt["weights"]
total = (f_ratio * w["required_findings"] +
         r_ratio * w["file_references"] +
         c_ratio * w["causal_chain"] +
         n_ratio * w["negative_checks"])

print("=== Final Score ===")
print(f"  Findings:  {f_ratio:.2f} * {w['required_findings']} = {f_ratio * w['required_findings']:.3f}")
print(f"  File refs: {r_ratio:.2f} * {w['file_references']} = {r_ratio * w['file_references']:.3f}")
print(f"  Causal:    {c_ratio:.2f} * {w['causal_chain']} = {c_ratio * w['causal_chain']:.3f}")
print(f"  Negative:  {n_ratio:.2f} * {w['negative_checks']} = {n_ratio * w['negative_checks']:.3f}")
print(f"  TOTAL:     {total:.2f}")

with open(REWARD_PATH, "w") as f:
    f.write(f"{total:.2f}\n")

print()
print(f"Tests completed - Score: {total:.2f}")
PYEOF
