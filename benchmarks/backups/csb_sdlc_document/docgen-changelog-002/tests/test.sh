#!/bin/bash
# Reward: checklist (0.0-1.0) — documentation quality score
set -euo pipefail

[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh
# Artifact mode: parse answer.json, extract analysis text
if [ -f /tmp/.artifact_only_mode ] && [ -f /tests/answer_json_verifier_lib.sh ]; then
    source /tests/answer_json_verifier_lib.sh
fi

mkdir -p /logs/verifier

OUTPUT_FILE="/workspace/RELEASE_NOTES.md"
# In artifact mode, populate expected output from answer.json analysis
if [ "${ARTIFACT_ONLY:-false}" = "true" ] && [ -f "${ANALYSIS_TEXT_FILE:-}" ]; then
    cp "$ANALYSIS_TEXT_FILE" "/workspace/RELEASE_NOTES.md"
    echo "[answer_json] Copied analysis text to /workspace/RELEASE_NOTES.md"
fi
EXTRA_FILES=""

# Fallback: search for any .md file the agent wrote
if [ ! -f "$OUTPUT_FILE" ]; then
    ALT=$(find /workspace -maxdepth 2 -name "*.md" ! -name "README*" ! -name "CONTRIBUTING*" 2>/dev/null | head -1)
    OUTPUT_FILE="${ALT:-$OUTPUT_FILE}"
fi

if [ ! -f "$OUTPUT_FILE" ]; then
    echo "No output file found at /workspace/RELEASE_NOTES.md"
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

# Write scorer script
cat > /tmp/_scorer.py << 'SCOREEOF'
import sys, re, json, os

output_path = sys.argv[1]
extra_paths = sys.argv[2:-1]
gt_path = sys.argv[-1]

try:
    content = open(output_path).read()
    gt = json.load(open(gt_path))
except Exception as e:
    print(f"Error reading files: {e}", file=sys.stderr)
    print("0.0", end="")
    sys.exit(0)

# Also read any extra source files (for inline doc tasks)
extra_content = ""
for ep in extra_paths:
    if ep != gt_path and os.path.isfile(ep):
        try:
            extra_content += "\n" + open(ep).read()
        except Exception:
            pass

full_content = content + "\n" + extra_content

weights = gt.get("weights", {})

def check_section(section_items):
    if not section_items:
        return 0.0
    total_weight = sum(item.get("weight", 1.0 / len(section_items)) for item in section_items)
    section_score = 0.0
    for item in section_items:
        item_weight = item.get("weight", 1.0 / len(section_items))
        patterns = item.get("patterns", [])
        matched = False
        for p in patterns:
            try:
                if re.search(p, full_content, re.MULTILINE | re.IGNORECASE):
                    matched = True
                    break
            except re.error:
                if p.lower() in full_content.lower():
                    matched = True
                    break
        if matched:
            section_score += item_weight / total_weight if total_weight > 0 else 0.0
            print(f"  PASS: {item['description']}", file=sys.stderr)
        else:
            print(f"  FAIL: {item['description']}", file=sys.stderr)
    return section_score

total_score = 0.0
for section_key, section_weight in weights.items():
    section_items = gt.get(section_key, [])
    section_score = check_section(section_items)
    contribution = section_score * float(section_weight)
    total_score += contribution
    print(f"Section '{section_key}': {section_score:.2f} * {section_weight} = {contribution:.3f}", file=sys.stderr)

total_score = min(1.0, max(0.0, total_score))
print(f"Total score: {total_score:.2f}", file=sys.stderr)
print(f"{total_score:.2f}", end="")

SCOREEOF

SCORE=$(python3 /tmp/_scorer.py "$OUTPUT_FILE" $EXTRA_FILES /tests/ground_truth.json 2>&1 | tail -1)
# Re-run to get clean score (stderr goes to log, stdout is score)
SCORE=$(python3 /tmp/_scorer.py "$OUTPUT_FILE" $EXTRA_FILES /tests/ground_truth.json 2>/dev/null)

echo "$SCORE" > /logs/verifier/reward.txt
echo "Score: $SCORE"
exit 0
