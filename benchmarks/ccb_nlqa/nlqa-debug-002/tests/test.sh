#!/bin/bash
# Reward: checklist (0.0-1.0) — weighted pattern matching against ground_truth.json
#
# SHARED SCORER TEMPLATE
# -----------------------
# Generalized from ccb_investigation's test.sh. Each task copies this file
# into its tests/ directory and configures it via environment variables or
# by editing the variables below.
#
# To use: copy to your task's tests/test.sh and set REPORT_PATH to the
# expected agent output path. Provide a ground_truth.json in the same
# tests/ directory.
#
# Scoring categories and their default weights (from ground_truth.json):
#   required_findings: 0.40  — key facts the agent must discover
#   file_references:   0.30  — specific code locations cited as evidence
#   causal_chain:      0.20  — logical chain of reasoning (ALL patterns must match)
#   negative_checks:   0.10  — patterns that must NOT appear (penalizes wrong conclusions)
#
# ground_truth.json schema:
# {
#   "required_findings": [{"description": "...", "patterns": ["regex1", ...], "weight": 1.0}],
#   "file_references":   [{"description": "...", "patterns": ["regex1", ...], "weight": 1.0}],
#   "causal_chain":      [{"description": "...", "patterns": ["regex1", ...], "weight": 1.0}],
#   "negative_checks":   [{"description": "...", "patterns": ["regex1", ...], "weight": 1.0}],
#   "weights": {
#     "required_findings": 0.40,
#     "file_references":   0.30,
#     "causal_chain":      0.20,
#     "negative_checks":   0.10
#   }
# }

set -e

# ── Configurable paths ────────────────────────────────────────────────────
# Override REPORT_PATH per suite:
#   investigation: /logs/agent/investigation.md
#   nlqa:          /logs/agent/investigation.md
#   security:      /logs/agent/triage.md
#   onboarding:    /logs/agent/onboarding.md
#   docgen:        /workspace/documentation.md
REPORT_PATH="${REPORT_PATH:-/logs/agent/investigation.md}"
GROUND_TRUTH="${GROUND_TRUTH:-/tests/ground_truth.json}"
REWARD_FILE="/logs/verifier/reward.txt"
MIN_REPORT_BYTES="${MIN_REPORT_BYTES:-100}"

mkdir -p /logs/verifier

# ── Check prerequisites ───────────────────────────────────────────────────
if [ ! -f "$GROUND_TRUTH" ]; then
    echo "ERROR: ground_truth.json not found at $GROUND_TRUTH"
    echo "0.0" > "$REWARD_FILE"
    exit 0
fi

if [ ! -f "$REPORT_PATH" ]; then
    echo "No agent output found at $REPORT_PATH"
    echo "Agent did not produce the required output."
    echo "0.0" > "$REWARD_FILE"
    exit 0
fi

REPORT_SIZE=$(wc -c < "$REPORT_PATH")
if [ "$REPORT_SIZE" -lt "$MIN_REPORT_BYTES" ]; then
    echo "Agent output is too short (${REPORT_SIZE} bytes, minimum ${MIN_REPORT_BYTES}). Likely incomplete."
    echo "0.0" > "$REWARD_FILE"
    exit 0
fi

echo "Scoring agent output ($REPORT_SIZE bytes)..."
echo "Report: $REPORT_PATH"
echo "Ground truth: $GROUND_TRUTH"
echo ""

# ── Delegate scoring to Python (avoids shell escaping issues with regex) ─
REPORT_PATH="$REPORT_PATH" GROUND_TRUTH="$GROUND_TRUTH" REWARD_FILE="$REWARD_FILE" \
python3 << 'PYEOF'
import json, os, re, sys

REPORT_PATH = os.environ["REPORT_PATH"]
GT_PATH = os.environ["GROUND_TRUTH"]
REWARD_PATH = os.environ["REWARD_FILE"]

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

def score_category(items, label, use_all=False, negate=False):
    """Score a category of checklist items. Returns (score, total) tuple."""
    print(f"=== {label} ===")
    score, total = 0.0, 0.0
    for item in items:
        total += item["weight"]
        if use_all:
            matched = check_all_patterns(item["patterns"], report)
        else:
            matched = check_any_pattern(item["patterns"], report)
        # Negative checks: PASS when pattern is NOT found
        passed = (not matched) if negate else matched
        if passed:
            score += item["weight"]
            print(f"  [x] {item['description']} (weight: {item['weight']})")
        else:
            tag = "FAIL: " if negate else ""
            suffix = " -- wrong conclusion found" if negate else ""
            print(f"  [ ] {tag}{item['description']} (weight: {item['weight']}){suffix}")
    ratio = score / total if total > 0 else (1.0 if negate else 0.0)
    print(f"  Score: {score:.2f} / {total:.2f} = {ratio:.2f}")
    print()
    return ratio

# ── Score each category ──────────────────────────────────────────────────
f_ratio = score_category(gt.get("required_findings", []), "Required Findings")
r_ratio = score_category(gt.get("file_references", []), "File References")
c_ratio = score_category(gt.get("causal_chain", []), "Causal Chain", use_all=True)
n_ratio = score_category(gt.get("negative_checks", []), "Negative Checks", negate=True)

# ── Compute weighted total ───────────────────────────────────────────────
w = gt.get("weights", {
    "required_findings": 0.40,
    "file_references": 0.30,
    "causal_chain": 0.20,
    "negative_checks": 0.10,
})
total = (f_ratio * w.get("required_findings", 0.40) +
         r_ratio * w.get("file_references", 0.30) +
         c_ratio * w.get("causal_chain", 0.20) +
         n_ratio * w.get("negative_checks", 0.10))

print("=== Final Score ===")
print(f"  Findings:  {f_ratio:.2f} * {w.get('required_findings', 0.40)} = {f_ratio * w.get('required_findings', 0.40):.3f}")
print(f"  File refs: {r_ratio:.2f} * {w.get('file_references', 0.30)} = {r_ratio * w.get('file_references', 0.30):.3f}")
print(f"  Causal:    {c_ratio:.2f} * {w.get('causal_chain', 0.20)} = {c_ratio * w.get('causal_chain', 0.20):.3f}")
print(f"  Negative:  {n_ratio:.2f} * {w.get('negative_checks', 0.10)} = {n_ratio * w.get('negative_checks', 0.10):.3f}")
print(f"  TOTAL:     {total:.2f}")

with open(REWARD_PATH, "w") as f:
    f.write(f"{total:.2f}\n")

print()
print(f"Tests completed - Score: {total:.2f}")
PYEOF
