#!/bin/bash
# Reward: semantic_similarity (0.0-1.0) — content, file references, and pattern matching
# Harbor test script for refactor_rename_01 — patch validation with fallback diff collection
#
# Primary (a): Check for explicit /logs/agent/patch.diff
# Fallback (b): Auto-generate diff from workspace changes in /ccb_crossrepo/src/
set -x
# NOTE: set -e intentionally NOT used — fallback logic requires graceful failure handling

PATCH_FILE="/logs/agent/patch.diff"
EXPECTED_CHANGES="/tests/expected_changes.json"
CORPUS_ROOT="/ccb_crossrepo"
REWARD_FILE="/logs/verifier/reward.txt"
VALIDATION_RESULT="/logs/verifier/validation_result.json"

echo "=== refactor_rename_01 Patch Validation ===" >&2
echo "" >&2

# ============================================
# Step 1: Locate or generate the patch
# ============================================
EFFECTIVE_PATCH="$PATCH_FILE"

if [ -f "$PATCH_FILE" ] && [ -s "$PATCH_FILE" ]; then
    echo "Found explicit patch at $PATCH_FILE ($(wc -l < "$PATCH_FILE") lines)" >&2
else
    echo "No patch at $PATCH_FILE — trying fallback diff collection..." >&2

    # Fallback: generate diff from git changes in the source repos
    FALLBACK_PATCH="/tmp/fallback_patch.diff"
    > "$FALLBACK_PATCH"

    for repo_dir in "$CORPUS_ROOT"/src/*/; do
        if [ -d "$repo_dir/.git" ]; then
            repo_name=$(basename "$repo_dir")
            echo "  Checking $repo_name for changes..." >&2
            cd "$repo_dir"
            git diff HEAD -- . >> "$FALLBACK_PATCH" 2>/dev/null || true
            git ls-files --others --exclude-standard | while read -r f; do
                if [ -f "$f" ]; then
                    echo "diff --git a/$f b/$f" >> "$FALLBACK_PATCH"
                    echo "new file mode 100644" >> "$FALLBACK_PATCH"
                    echo "--- /dev/null" >> "$FALLBACK_PATCH"
                    echo "+++ b/$f" >> "$FALLBACK_PATCH"
                    wc_lines=$(wc -l < "$f")
                    echo "@@ -0,0 +1,$wc_lines @@" >> "$FALLBACK_PATCH"
                    sed 's/^/+/' "$f" >> "$FALLBACK_PATCH"
                fi
            done
        fi
    done

    if [ -s "$FALLBACK_PATCH" ]; then
        echo "Fallback diff collected: $(wc -l < "$FALLBACK_PATCH") lines" >&2
        EFFECTIVE_PATCH="$FALLBACK_PATCH"
        cp "$FALLBACK_PATCH" "/logs/agent/patch.diff" 2>/dev/null || true
    else
        echo "ERROR: No changes found in any source repository" >&2
        echo "0.0" > "$REWARD_FILE"
        exit 0
    fi
fi

# ============================================
# Step 2: Validate the patch
# ============================================
echo "" >&2
echo "Validating patch against expected changes..." >&2

# Inline validation — self-contained, no external dependencies
echo "Using inline validation..." >&2
python3 - "$EFFECTIVE_PATCH" "$EXPECTED_CHANGES" "$VALIDATION_RESULT" << 'PYEOF'
import json, re, sys
from pathlib import Path

patch_path, expected_path, output_path = sys.argv[1], sys.argv[2], sys.argv[3]

with open(patch_path) as f:
    patch_text = f.read()
with open(expected_path) as f:
    expected = json.load(f)

files = {}
current = None
for line in patch_text.splitlines():
    if line.startswith("diff --git "):
        parts = line.split(" b/", 1)
        if len(parts) == 2:
            current = parts[1]
            files[current] = {"added": [], "removed": []}
    elif current:
        if line.startswith("+") and not line.startswith("+++"):
            files[current]["added"].append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            files[current]["removed"].append(line[1:])

# Fallback: if no "diff --git" headers found, parse standard unified diff
# format using "--- a/" and "+++ b/" lines to identify files.
if not files:
    current = None
    for line in patch_text.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
            files[current] = {"added": [], "removed": []}
        elif line.startswith("+++ ") and not line.startswith("+++ /dev/null"):
            # Handle "+++ path" without b/ prefix
            current = line[4:].lstrip("b/") if line[4:].startswith("b/") else line[4:]
            files[current] = {"added": [], "removed": []}
        elif current:
            if line.startswith("+") and not line.startswith("+++"):
                files[current]["added"].append(line[1:])
            elif line.startswith("-") and not line.startswith("---"):
                files[current]["removed"].append(line[1:])

if not files:
    result = {"overall_score": 0.0, "error": "No files in patch"}
else:
    exp_files = expected.get("expected_files", [])
    matched = []
    for ef in exp_files:
        for pf in files:
            if pf == ef or pf.endswith(ef) or ef.endswith(pf):
                matched.append(ef)
                break
    file_cov = len(matched) / len(exp_files) if exp_files else 1.0

    all_added = "\n".join(l for f in files.values() for l in f["added"])
    all_removed = "\n".join(l for f in files.values() for l in f["removed"])
    pat_scores = []
    pat_results = {"removed": {}, "added": {}}
    for p in expected.get("expected_patterns", {}).get("removed", []):
        try: found = bool(re.search(p, all_removed))
        except: found = p in all_removed
        pat_results["removed"][p] = found
        pat_scores.append(1.0 if found else 0.0)
    for p in expected.get("expected_patterns", {}).get("added", []):
        try: found = bool(re.search(p, all_added))
        except: found = p in all_added
        pat_results["added"][p] = found
        pat_scores.append(1.0 if found else 0.0)
    pat_score = sum(pat_scores) / len(pat_scores) if pat_scores else 1.0

    result = {
        "overall_score": round(0.4 * file_cov + 0.6 * pat_score, 4),
        "file_coverage": round(file_cov, 4),
        "pattern_score": round(pat_score, 4),
        "files_in_patch": list(files.keys()),
        "files_matched": matched,
        "pattern_results": pat_results,
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
