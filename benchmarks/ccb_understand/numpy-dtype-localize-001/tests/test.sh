#!/bin/bash
# Reward: semantic_similarity (0.0-1.0) — content, file references, and pattern matching
# Harbor test script for bug_localization_01 — analysis document validation
#
# This is an ANALYSIS task, not a code modification task.
# The agent writes BUG_ANALYSIS.md with its findings.
# We validate the analysis contains expected file references and keywords.

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

set -x
# NOTE: set -e intentionally NOT used — fallback logic requires graceful failure handling

EXPECTED_CHANGES="/tests/expected_changes.json"
REWARD_FILE="/logs/verifier/reward.txt"
VALIDATION_RESULT="/logs/verifier/validation_result.json"

echo "=== bug_localization_01 Analysis Validation ===" >&2
echo "" >&2

# ============================================
# Step 1: Find the analysis document
# ============================================
ANALYSIS_FILE=""
for candidate in \
    /workspace/BUG_ANALYSIS.md \
    /workspace/bug_analysis.md \
    /workspace/Bug_Analysis.md \
    /logs/agent/BUG_ANALYSIS.md \
    /ccb_crossrepo/src/BUG_ANALYSIS.md \
    /workspace/analysis.md \
    /workspace/ANALYSIS.md; do
    if [ -f "$candidate" ] && [ -s "$candidate" ]; then
        ANALYSIS_FILE="$candidate"
        break
    fi
done

# Also check for any .md file in /workspace if no exact match
if [ -z "$ANALYSIS_FILE" ]; then
    for f in /workspace/*.md; do
        if [ -f "$f" ] && [ -s "$f" ]; then
            ANALYSIS_FILE="$f"
            echo "No BUG_ANALYSIS.md found, using $f" >&2
            break
        fi
    done
fi

if [ -z "$ANALYSIS_FILE" ]; then
    echo "ERROR: No analysis document found in /workspace/ or /logs/agent/" >&2
    echo "0.0" > "$REWARD_FILE"
    echo '{"overall_score": 0.0, "error": "No analysis document found"}' > "$VALIDATION_RESULT"
    exit 0
fi

echo "Found analysis at: $ANALYSIS_FILE ($(wc -l < "$ANALYSIS_FILE") lines)" >&2

# ============================================
# Step 2: Validate content against expected_changes.json
# ============================================
python3 - "$ANALYSIS_FILE" "$EXPECTED_CHANGES" "$VALIDATION_RESULT" << 'PYEOF'
import json, re, sys
from pathlib import Path

analysis_path, expected_path, output_path = sys.argv[1], sys.argv[2], sys.argv[3]

with open(analysis_path) as f:
    analysis_text = f.read()
with open(expected_path) as f:
    expected = json.load(f)

scores = []
details = {}

# Check expected_content keywords (case-insensitive)
expected_content = expected.get("expected_content", [])
content_hits = {}
for keyword in expected_content:
    found = keyword.lower() in analysis_text.lower()
    content_hits[keyword] = found
    scores.append(1.0 if found else 0.0)

details["content_keywords"] = content_hits
content_score = sum(1.0 for v in content_hits.values() if v) / len(content_hits) if content_hits else 0.0

# Check expected_files are mentioned in the analysis
expected_files = expected.get("expected_files", [])
file_hits = {}
for filepath in expected_files:
    # Check for full path, basename, or partial path
    basename = Path(filepath).name
    parent_and_name = str(Path(filepath).parent.name) + "/" + basename
    found = (
        filepath in analysis_text
        or basename in analysis_text
        or parent_and_name in analysis_text
    )
    file_hits[filepath] = found
    scores.append(1.0 if found else 0.0)

details["file_references"] = file_hits
file_score = sum(1.0 for v in file_hits.values() if v) / len(file_hits) if file_hits else 0.0

# Check expected_patterns (root_cause_files, entry_point_files)
pattern_hits = {}
for category, patterns in expected.get("expected_patterns", {}).items():
    for pattern in patterns:
        try:
            found = bool(re.search(pattern, analysis_text))
        except re.error:
            found = pattern in analysis_text
        pattern_hits[f"{category}:{pattern}"] = found
        scores.append(1.0 if found else 0.0)

details["pattern_references"] = pattern_hits
pattern_score = sum(1.0 for v in pattern_hits.values() if v) / len(pattern_hits) if pattern_hits else 0.0

# Overall: 40% content keywords, 30% file references, 30% pattern references
overall = 0.4 * content_score + 0.3 * file_score + 0.3 * pattern_score

result = {
    "overall_score": round(overall, 4),
    "content_score": round(content_score, 4),
    "file_reference_score": round(file_score, 4),
    "pattern_reference_score": round(pattern_score, 4),
    "details": details,
    "analysis_file": analysis_path,
    "analysis_lines": len(analysis_text.splitlines()),
}

Path(output_path).parent.mkdir(parents=True, exist_ok=True)
with open(output_path, "w") as f:
    json.dump(result, f, indent=2)
print(json.dumps(result, indent=2), file=sys.stderr)
print(result["overall_score"])
PYEOF

if [ -f "$VALIDATION_RESULT" ]; then
    REWARD=$(python3 -c "import json; print(json.load(open('$VALIDATION_RESULT'))['overall_score'])" 2>/dev/null)
    if [ -n "$REWARD" ]; then
        echo "$REWARD" > "$REWARD_FILE"
        echo "Validation complete — Reward: $REWARD" >&2
    else
        echo "0.0" > "$REWARD_FILE"
        echo "WARNING: Could not parse validation result, defaulting to 0.0" >&2
    fi
else
    echo "0.0" > "$REWARD_FILE"
    echo "WARNING: No validation result file generated, defaulting to 0.0" >&2
fi
