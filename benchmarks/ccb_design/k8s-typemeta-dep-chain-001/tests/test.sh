#!/bin/bash
# Reward: Partial credit (0.0-1.0) — each correct link in the chain scores independently
#
# DEPENDENCY CHAIN SCORER
# -----------------------
# Scores agent output by comparing each step in the dependency chain against
# ground truth. Each step is worth an equal fraction of the total score.
# Matching is fuzzy on line numbers (+/- tolerance) and exact on repo/file.

set -e

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh


OUTPUT_PATH="/workspace/chain.json"
GROUND_TRUTH="/tests/ground_truth.json"
REWARD_FILE="/logs/verifier/reward.txt"
LINE_TOLERANCE=50  # +/- 50 lines for line number matching

mkdir -p /logs/verifier

# ── Check prerequisites ───────────────────────────────────────────────────
if [ ! -f "$GROUND_TRUTH" ]; then
    echo "ERROR: ground_truth.json not found at $GROUND_TRUTH"
    echo "0.0" > "$REWARD_FILE"
    exit 0
fi

if [ ! -f "$OUTPUT_PATH" ]; then
    echo "No agent output found at $OUTPUT_PATH"
    echo "Agent did not produce the required chain.json file."
    echo "0.0" > "$REWARD_FILE"
    exit 0
fi

echo "Scoring dependency chain..."
echo "Output: $OUTPUT_PATH"
echo "Ground truth: $GROUND_TRUTH"
echo ""

# ── Delegate scoring to Python ────────────────────────────────────────────
OUTPUT_PATH="$OUTPUT_PATH" GROUND_TRUTH="$GROUND_TRUTH" \
REWARD_FILE="$REWARD_FILE" LINE_TOLERANCE="$LINE_TOLERANCE" \
python3 << 'PYEOF'
import json, os, re, sys

OUTPUT_PATH = os.environ["OUTPUT_PATH"]
GT_PATH = os.environ["GROUND_TRUTH"]
REWARD_PATH = os.environ["REWARD_FILE"]
LINE_TOLERANCE = int(os.environ.get("LINE_TOLERANCE", "50"))

def write_reward(score):
    """Write score to reward file and print summary."""
    with open(REWARD_PATH, "w") as f:
        f.write(f"{score:.2f}\n")
    print(f"\nTests completed - Score: {score:.2f}")

def strip_code_fences(text):
    """Strip markdown code fences if agent wrapped JSON in ```json blocks."""
    m = re.search(r'```(?:json)?\s*\n(.*?)```', text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()

def normalize_path(path):
    """Normalize file paths (remove leading ./ or /workspace/)."""
    path = path.strip()
    path = re.sub(r'^\./', '', path)
    path = re.sub(r'^/workspace/[^/]+/', '', path)
    return path

def lines_match(line1, line2, tolerance):
    """Check if two line numbers match within tolerance (both can be None)."""
    if line1 is None or line2 is None:
        return True  # Don't penalize if line number not provided
    return abs(int(line1) - int(line2)) <= tolerance

# ── Main scoring logic (wrapped in try/except for reward safety) ─────────
try:
    # ── Load ground truth ────────────────────────────────────────────────
    with open(GT_PATH) as f:
        gt = json.load(f)

    expected_steps = gt.get("steps", [])
    if not expected_steps:
        print("ERROR: ground_truth.json must have a 'steps' array")
        write_reward(0.0)
        sys.exit(0)

    num_expected = len(expected_steps)

    # ── Load agent output ────────────────────────────────────────────────
    try:
        with open(OUTPUT_PATH) as f:
            raw = f.read()
        raw = strip_code_fences(raw)
        reported_steps = json.loads(raw)
        if not isinstance(reported_steps, list):
            print("Agent output is not a JSON array — scoring as empty.")
            reported_steps = []
    except (json.JSONDecodeError, ValueError, FileNotFoundError, OSError) as e:
        print(f"Could not read/parse agent output: {e}")
        reported_steps = []

    num_reported = len(reported_steps)

    if num_reported == 0:
        print("Agent output is empty — no chain steps to score.")
        print(f"Expected {num_expected} steps.")
        write_reward(0.0)
        sys.exit(0)

    # ── Score each step ──────────────────────────────────────────────────
    correct_steps = 0
    step_details = []

    for i, expected in enumerate(expected_steps, start=1):
        # Find matching reported step by step number or position
        reported = None
        for r in reported_steps:
            if r.get("step") == expected.get("step", i):
                reported = r
                break

        if not reported and i <= num_reported:
            # Fallback: match by position if step field missing
            reported = reported_steps[i-1]

        if not reported:
            step_details.append({
                "step": i,
                "status": "MISSING",
                "expected": expected
            })
            continue

        # Check each field
        repo_match = expected.get("repo", "").strip() == reported.get("repo", "").strip()
        file_match = normalize_path(expected.get("file", "")) == normalize_path(reported.get("file", ""))
        line_match = lines_match(expected.get("line"), reported.get("line"), LINE_TOLERANCE)

        all_match = repo_match and file_match and line_match

        if all_match:
            correct_steps += 1
            status = "CORRECT"
        else:
            status = "PARTIAL" if (repo_match or file_match) else "WRONG"

        step_details.append({
            "step": i,
            "status": status,
            "repo_match": repo_match,
            "file_match": file_match,
            "line_match": line_match,
            "expected": expected,
            "reported": reported
        })

    # ── Compute score ────────────────────────────────────────────────────
    # Each step is worth equal credit
    score = correct_steps / num_expected if num_expected > 0 else 0.0

    # Write reward BEFORE verbose printing (ensures reward even if printing fails)
    write_reward(score)

    # ── Print detailed results ───────────────────────────────────────────
    print(f"\n=== Dependency Chain Scoring ===")
    print(f"  Expected steps: {num_expected}")
    print(f"  Reported steps: {num_reported}")
    print(f"  Line tolerance: +/- {LINE_TOLERANCE}")
    print()
    print("=== Step-by-Step Results ===")
    for detail in step_details:
        status = detail["status"]
        symbol = "[+]" if status == "CORRECT" else "[-]" if status == "WRONG" else "[~]"
        print(f"\nStep {detail['step']}: {symbol} {status}")

        exp = detail["expected"]
        print(f"  Expected: {exp.get('repo')} / {exp.get('file')} : {exp.get('line')}")
        print(f"            {exp.get('context', 'N/A')}")

        if "reported" in detail:
            rep = detail["reported"]
            print(f"  Reported: {rep.get('repo')} / {rep.get('file')} : {rep.get('line')}")
            print(f"            {rep.get('context', 'N/A')}")

            if status != "MISSING":
                print(f"  Match: repo={detail['repo_match']}, file={detail['file_match']}, line={detail['line_match']}")
        else:
            print(f"  Reported: (missing)")

    print(f"\n=== Summary ===")
    print(f"  Correct steps: {correct_steps}/{num_expected}")
    print(f"  Score: {score:.2f}")

except Exception as exc:
    print(f"ERROR: Scoring failed with exception: {exc}", file=sys.stderr)
    # Safety net: always write a reward file
    try:
        write_reward(0.0)
    except Exception:
        # Last resort: direct write
        with open(REWARD_PATH, "w") as f:
            f.write("0.00\n")
PYEOF
