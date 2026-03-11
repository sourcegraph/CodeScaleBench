#!/bin/bash
# answer_json_verifier_lib.sh — Unified answer.json verifier for artifact configs.
#
# Source this at the TOP of test.sh. It detects /tmp/.artifact_only_mode and:
#   1. Validates /workspace/answer.json exists and is valid JSON
#   2. Extracts analysis.reasoning → $ANALYSIS_TEXT_FILE (for keyword/pattern scoring)
#   3. Extracts analysis.files_examined → $ANALYSIS_FILES_FILE (for IR metrics)
#   4. If changes[] has diffs: applies diffs directly to /repo_full (zero-copy, container is ephemeral)
#   5. Exports VERIFY_REPO, ARTIFACT_ONLY, ANALYSIS_TEXT_FILE, etc.
#
# For non-artifact-only runs, this script is a no-op that sets safe defaults.
#
# Usage in test.sh:
#   #!/bin/bash
#   set -e
#   # Artifact mode: parse answer.json, apply patches, export analysis
#   if [ -f /tmp/.artifact_only_mode ] && [ -f /tests/answer_json_verifier_lib.sh ]; then
#       source /tests/answer_json_verifier_lib.sh
#   fi
#   # ... rest of test.sh uses $VERIFY_REPO, $ANALYSIS_TEXT_FILE, etc. ...

if [ ! -f /tmp/.artifact_only_mode ]; then
    # Not in artifact-only mode — export defaults for backward compat
    export VERIFY_REPO="${VERIFY_REPO:-/workspace}"
    export ARTIFACT_ONLY=false
    export ANALYSIS_TEXT_FILE=""
    export ANALYSIS_FILES_FILE=""
    export ANSWER_JSON=""
    export ANSWER_JSON_MISSING=false
    export ANSWER_JSON_NO_CHANGES=false
    return 0 2>/dev/null || true
fi

echo "[answer_json_verifier] Detected artifact-only mode"
export ARTIFACT_ONLY=true
export ANSWER_JSON="/workspace/answer.json"
export ANALYSIS_TEXT_FILE="/tmp/analysis.txt"
export ANALYSIS_FILES_FILE="/tmp/analysis_files.json"
export ANSWER_JSON_MISSING=false
export ANSWER_JSON_NO_CHANGES=false

answer_json_fail_closed_if_missing() {
    if [ "${ARTIFACT_ONLY:-false}" = "true" ] && [ "${ANSWER_JSON_MISSING:-false}" = "true" ]; then
        mkdir -p /logs/verifier
        printf '0.0\n' > /logs/verifier/reward.txt
        echo "[answer_json_verifier] Scored 0.0 because answer.json is missing"
        exit 0
    fi
}

answer_json_fail_closed_if_missing_or_no_changes() {
    if [ "${ARTIFACT_ONLY:-false}" = "true" ] && {
        [ "${ANSWER_JSON_MISSING:-false}" = "true" ] || [ "${ANSWER_JSON_NO_CHANGES:-false}" = "true" ]
    }; then
        mkdir -p /logs/verifier
        printf '0.0\n' > /logs/verifier/reward.txt
        echo "[answer_json_verifier] Scored 0.0 because answer.json has no usable artifact payload"
        exit 0
    fi
}

answer_json_copy_analysis_text() {
    local target_path="$1"
    if [ "${ARTIFACT_ONLY:-false}" = "true" ] && [ -f "${ANALYSIS_TEXT_FILE:-}" ]; then
        mkdir -p "$(dirname "$target_path")"
        cp "$ANALYSIS_TEXT_FILE" "$target_path"
        echo "[answer_json_verifier] Copied analysis text to $target_path"
    fi
}

rm -f /tmp/.answer_json_no_changes /tmp/.answer_json_verify_repo

# ── Validate answer.json ──────────────────────────────────────────────────

if [ ! -f "$ANSWER_JSON" ]; then
    echo "[answer_json_verifier] ERROR: /workspace/answer.json not found"
    echo "[answer_json_verifier] Agent did not produce required artifact"
    export VERIFY_REPO="${VERIFY_REPO:-/workspace}"
    export ANSWER_JSON_MISSING=true
    # Signal to test.sh that there's no output — it should score 0
    return 0 2>/dev/null || true
fi

# Validate JSON and extract fields using Python
python3 - "$ANSWER_JSON" <<'PYEOF'
import json, sys, os, subprocess, tempfile, re

answer_path = sys.argv[1]
analysis_text_file = os.environ.get("ANALYSIS_TEXT_FILE", "/tmp/analysis.txt")
analysis_files_file = os.environ.get("ANALYSIS_FILES_FILE", "/tmp/analysis_files.json")

# ── Parse answer.json ─────────────────────────────────────────────────────
try:
    with open(answer_path) as f:
        raw = f.read()

    # Strip markdown code fences if agent wrapped JSON in ```json blocks
    m = re.search(r'```(?:json)?\s*\n(.*?)```', raw, re.DOTALL)
    if m:
        raw = m.group(1).strip()

    answer = json.loads(raw)
    if not isinstance(answer, dict):
        print("[answer_json_verifier] WARNING: answer.json is not a JSON object", file=sys.stderr)
        answer = {}
except (json.JSONDecodeError, ValueError) as e:
    print(f"[answer_json_verifier] ERROR: Failed to parse answer.json: {e}", file=sys.stderr)
    answer = {}
except FileNotFoundError:
    print("[answer_json_verifier] ERROR: answer.json not found", file=sys.stderr)
    answer = {}

# ── Extract analysis fields ───────────────────────────────────────────────
analysis = answer.get("analysis", {})
if not isinstance(analysis, dict):
    analysis = {}

# Build analysis text from summary + reasoning (what verifiers will grep)
parts = []
summary = analysis.get("summary", "")
if summary:
    parts.append(summary)
reasoning = analysis.get("reasoning", "")
if reasoning:
    parts.append(reasoning)
analysis_text = "\n\n".join(parts)

with open(analysis_text_file, "w") as f:
    f.write(analysis_text)
print(f"[answer_json_verifier] Wrote analysis text ({len(analysis_text)} chars) to {analysis_text_file}")

# Extract files_examined for IR metrics
files_examined = analysis.get("files_examined", [])
if not isinstance(files_examined, list):
    files_examined = []
with open(analysis_files_file, "w") as f:
    json.dump(files_examined, f, indent=2)
print(f"[answer_json_verifier] Wrote {len(files_examined)} examined files to {analysis_files_file}")

# ── Extract and apply diffs from changes[] ────────────────────────────────
changes = answer.get("changes", [])
if not isinstance(changes, list):
    changes = []

if not changes:
    print("[answer_json_verifier] No changes[] in answer.json (analysis-only task)")
    # Signal no patches needed
    with open("/tmp/.answer_json_no_changes", "w") as f:
        f.write("1")

# ── Generate synthetic review.json for code-review verifiers ──────────────
# Code-review verifiers expect /workspace/review.json with [{file, description, fix_patch}]
# Generate this from answer.json changes[] so existing F1 scoring works unchanged.
if changes:
    review_entries = []
    for change in changes:
        entry = {
            "file": change.get("file", ""),
            "description": change.get("description", ""),
            "fix_patch": change.get("diff", ""),
        }
        review_entries.append(entry)
    review_json_path = "/workspace/review.json"
    with open(review_json_path, "w") as f:
        json.dump(review_entries, f, indent=2)
    print(f"[answer_json_verifier] Generated synthetic review.json ({len(review_entries)} entries)")

# ── Extract new-file diffs to /workspace/ ─────────────────────────────────
# For find-and-prove tasks: agent writes regression tests as new-file diffs.
# Extract file content from diffs like "--- /dev/null\n+++ b/regression_test.py"
# and write directly to /workspace/.
new_files_written = 0
for change in changes:
    diff_text = change.get("diff", "")
    file_path = change.get("file", "")
    if not diff_text or not file_path:
        continue

    # Detect new-file diff: starts from /dev/null
    if "/dev/null" in diff_text:
        # Extract added lines (lines starting with +, excluding +++ header)
        lines = diff_text.split("\n")
        content_lines = []
        in_hunk = False
        for line in lines:
            if line.startswith("@@"):
                in_hunk = True
                continue
            if in_hunk:
                if line.startswith("+"):
                    content_lines.append(line[1:])  # Strip leading +
                elif line.startswith("-"):
                    pass  # skip removed lines (shouldn't exist in new-file)
                elif line.startswith("\\"):
                    pass  # "\ No newline at end of file"
                else:
                    content_lines.append(line)  # context line

        if content_lines:
            # Determine target path — use file field, write to /workspace/
            target = os.path.join("/workspace", os.path.basename(file_path))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "w") as f:
                f.write("\n".join(content_lines))
                if content_lines and not content_lines[-1] == "":
                    f.write("\n")
            new_files_written += 1
            print(f"[answer_json_verifier] Extracted new file: {target}")

if new_files_written > 0:
    print(f"[answer_json_verifier] Extracted {new_files_written} new files to /workspace/")

# ── Generate fault_localization_result.json ────────────────────────────────
# Fault-loc verifiers expect /workspace/fault_localization_result.json with
# {buggy_files, buggy_functions, reasoning, confidence}. Populate from analysis.
if analysis:
    fl_result = {}
    # buggy_files: extract from files_examined
    fl_files = [fe.get("path", "") for fe in files_examined if fe.get("path")]
    if fl_files:
        fl_result["buggy_files"] = fl_files
    # buggy_functions: look for a "functions" or "buggy_functions" key in analysis
    fl_funcs = analysis.get("buggy_functions", analysis.get("functions", []))
    if isinstance(fl_funcs, list) and fl_funcs:
        fl_result["buggy_functions"] = fl_funcs
    # reasoning: use the full analysis text
    if reasoning:
        fl_result["reasoning"] = reasoning
    # confidence: look for a confidence key
    confidence = analysis.get("confidence", None)
    if isinstance(confidence, (int, float)):
        fl_result["confidence"] = confidence
    # Only write if we have substantive content
    fl_path = "/workspace/fault_localization_result.json"
    if fl_result and not os.path.exists(fl_path):
        with open(fl_path, "w") as f:
            json.dump(fl_result, f, indent=2)
        print(f"[answer_json_verifier] Generated fault_localization_result.json")

# ── Apply diffs directly to /repo_full (zero-copy) ───────────────────────
if not changes:
    sys.exit(0)

# Apply diffs in-place — container is ephemeral, no need to preserve /repo_full
repo_full = "/repo_full"
if not os.path.isdir(repo_full):
    # Fallback to /workspace when /repo_full is unavailable (e.g. non-Harbor harnesses)
    repo_full = os.environ.get("TASK_REPO_ROOT") or os.environ.get("VERIFY_REPO") or "/workspace"
if not os.path.isdir(repo_full):
    print(f"[answer_json_verifier] WARNING: neither /repo_full nor /workspace found. Cannot apply diffs.")
    with open("/tmp/.answer_json_no_changes", "w") as f:
        f.write("1")
    sys.exit(0)
verify_repo = repo_full

# Ensure verifier (root) can write to repo_full
subprocess.run(["chmod", "-R", "u+w", repo_full], capture_output=True)
print(f"[answer_json_verifier] Applying diffs to {repo_full} (in-place, zero-copy)...")
subprocess.run(
    ["git", "config", "--global", "--add", "safe.directory", repo_full],
    capture_output=True
)

# Apply each diff
applied = 0
failed = 0

for entry in changes:
    diff_text = entry.get("diff", "")
    if not diff_text or not diff_text.strip():
        continue

    file_name = entry.get("file", "unknown")

    with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False, dir='/tmp') as pf:
        pf.write(diff_text)
        pf.flush()
        pf_path = pf.name

    # Try git apply (strictest)
    result = subprocess.run(
        ["git", "apply", "--allow-empty", pf_path],
        cwd=verify_repo, capture_output=True, text=True
    )
    if result.returncode == 0:
        applied += 1
        os.unlink(pf_path)
        print(f"[answer_json_verifier] Applied diff for {file_name} (git apply)")
        continue

    # Fallback: patch -p1 --fuzz=3
    result = subprocess.run(
        ["patch", "-p1", "--fuzz=3", "-i", pf_path],
        cwd=verify_repo, capture_output=True, text=True
    )
    if result.returncode == 0:
        applied += 1
        os.unlink(pf_path)
        print(f"[answer_json_verifier] Applied diff for {file_name} (patch -p1)")
        continue

    # Fallback: git apply --3way
    result = subprocess.run(
        ["git", "apply", "--allow-empty", "--3way", pf_path],
        cwd=verify_repo, capture_output=True, text=True
    )
    if result.returncode == 0:
        applied += 1
        os.unlink(pf_path)
        print(f"[answer_json_verifier] Applied diff for {file_name} (git apply --3way)")
        continue

    failed += 1
    print(f"[answer_json_verifier] WARNING: Diff for {file_name} failed to apply", file=sys.stderr)
    os.unlink(pf_path)

print(f"[answer_json_verifier] Diffs applied: {applied}, failed: {failed}")

# Write verify_repo path for shell to pick up
with open("/tmp/.answer_json_verify_repo", "w") as f:
    f.write(verify_repo)
PYEOF

# Pick up VERIFY_REPO from Python output
if [ -f /tmp/.answer_json_no_changes ]; then
    export ANSWER_JSON_NO_CHANGES=true
fi
if [ -f /tmp/.answer_json_verify_repo ]; then
    export VERIFY_REPO="$(cat /tmp/.answer_json_verify_repo)"
    cd "$VERIFY_REPO"
    echo "[answer_json_verifier] VERIFY_REPO set to $VERIFY_REPO"
elif [ -f /tmp/.answer_json_no_changes ]; then
    # Analysis-only: no repo copy needed, use /workspace or /repo_full as fallback
    export VERIFY_REPO="${VERIFY_REPO:-/workspace}"
    echo "[answer_json_verifier] Analysis-only mode, VERIFY_REPO=$VERIFY_REPO"
else
    export VERIFY_REPO="${VERIFY_REPO:-/workspace}"
    echo "[answer_json_verifier] WARNING: Using fallback VERIFY_REPO=$VERIFY_REPO"
fi

# Clean up temp markers
rm -f /tmp/.answer_json_verify_repo /tmp/.answer_json_no_changes

echo "[answer_json_verifier] Library loaded (ARTIFACT_ONLY=$ARTIFACT_ONLY, VERIFY_REPO=$VERIFY_REPO)"
