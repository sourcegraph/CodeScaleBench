#!/bin/bash
# Artifact-only verifier helper: apply patches from agent artifacts to /repo_full copy.
#
# Source this at the TOP of test.sh for artifact-only mode. It detects
# /tmp/.artifact_only_mode and:
#   1. Uses /repo_full directly for scoring (zero-copy, container is ephemeral)
#   2. Exports VERIFY_REPO for downstream fix-pattern checks
#   3. Provides apply_patches_from_review_json() to apply fix_patch fields
#   4. Provides apply_patch_file() to apply standalone .patch files
#
# For non-artifact-only runs (legacy or sg_only), this script is a no-op.
#
# Usage in test.sh:
#   #!/bin/bash
#   set -e
#   # Legacy sg_only support (no-op if not in sg_only mode)
#   [ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh
#   # Artifact-only support
#   [ -f /tmp/.artifact_only_mode ] && [ -f /tests/artifact_verifier_lib.sh ] && source /tests/artifact_verifier_lib.sh
#   # ... rest of test.sh uses $VERIFY_REPO for file checks ...

if [ ! -f /tmp/.artifact_only_mode ]; then
    # Not in artifact-only mode — export VERIFY_REPO as /workspace for backward compat
    export VERIFY_REPO="${VERIFY_REPO:-/workspace}"
    export ARTIFACT_ONLY=false
    return 0 2>/dev/null || true
fi

echo "[artifact_verifier] Detected artifact-only mode"
export ARTIFACT_ONLY=true

# Use /repo_full directly — container is ephemeral, no need to preserve pristine copy
if [ -d /repo_full ]; then
    chmod -R u+w /repo_full 2>/dev/null || true
    export VERIFY_REPO="/repo_full"
    cd /repo_full
    git config --global --add safe.directory /repo_full 2>/dev/null || true
    echo "[artifact_verifier] Scoring repo ready at $VERIFY_REPO (zero-copy)"
else
    echo "[artifact_verifier] WARNING: /repo_full not found. Using /workspace as fallback."
    export VERIFY_REPO="/workspace"
fi

# ── Patch application functions ──────────────────────────────

# Apply a single unified diff string to VERIFY_REPO.
# Returns 0 on success, 1 on failure.
apply_single_patch() {
    local patch_text="$1"
    local patch_file="/tmp/artifact_patch_$$.patch"

    echo "$patch_text" > "$patch_file"

    # Try git apply first (strictest)
    if cd "$VERIFY_REPO" && git apply --allow-empty "$patch_file" 2>/dev/null; then
        echo "[artifact_verifier] Patch applied via git apply"
        rm -f "$patch_file"
        return 0
    fi

    # Fallback: patch with fuzz
    if cd "$VERIFY_REPO" && patch -p1 --fuzz=3 -i "$patch_file" 2>/dev/null; then
        echo "[artifact_verifier] Patch applied via patch -p1 --fuzz=3"
        rm -f "$patch_file"
        return 0
    fi

    # Fallback: git apply with less strict options
    if cd "$VERIFY_REPO" && git apply --allow-empty --3way "$patch_file" 2>/dev/null; then
        echo "[artifact_verifier] Patch applied via git apply --3way"
        rm -f "$patch_file"
        return 0
    fi

    echo "[artifact_verifier] WARNING: Patch failed to apply"
    rm -f "$patch_file"
    return 1
}

# Apply a standalone .patch file to VERIFY_REPO.
# Usage: apply_patch_file /workspace/solution.patch
apply_patch_file() {
    local patch_path="$1"
    if [ ! -f "$patch_path" ]; then
        echo "[artifact_verifier] Patch file not found: $patch_path"
        return 1
    fi

    local content
    content="$(cat "$patch_path")"
    apply_single_patch "$content"
}

# Extract and apply fix_patch fields from a review.json file.
# Usage: apply_patches_from_review_json /workspace/review.json
# Returns the number of successfully applied patches.
apply_patches_from_review_json() {
    local review_path="$1"
    if [ ! -f "$review_path" ]; then
        echo "[artifact_verifier] review.json not found: $review_path"
        echo "0"
        return 1
    fi

    # Use Python to parse JSON and extract/apply patches
    python3 - "$review_path" "$VERIFY_REPO" <<'PYEOF'
import json, sys, os, subprocess, tempfile, re

review_path = sys.argv[1]
verify_repo = sys.argv[2]

# Parse review.json with nested-object fallback
try:
    with open(review_path) as f:
        raw = f.read()
    # Strip markdown code fences
    m = re.search(r'```(?:json)?\s*\n(.*?)```', raw, re.DOTALL)
    if m:
        raw = m.group(1).strip()
    reported = json.loads(raw)

    # Handle nested objects: {"defects": [...]}, {"review": {"defects": [...]}}
    if isinstance(reported, dict):
        for key in ("defects", "findings", "issues", "review"):
            val = reported.get(key, None)
            if isinstance(val, list):
                reported = val
                break
            elif isinstance(val, dict):
                for k2 in ("defects", "findings", "issues"):
                    v2 = val.get(k2, None)
                    if isinstance(v2, list):
                        reported = v2
                        break
                if isinstance(reported, list):
                    break
    if not isinstance(reported, list):
        reported = []
except Exception as e:
    print(f"[artifact_verifier] Failed to parse review.json: {e}", file=sys.stderr)
    reported = []

applied = 0
failed = 0

for entry in reported:
    patch_text = entry.get("fix_patch", "")
    if not patch_text or not patch_text.strip():
        continue

    # Write patch to temp file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.patch', delete=False, dir='/tmp') as pf:
        pf.write(patch_text)
        pf.flush()
        pf_path = pf.name

    # Try git apply
    result = subprocess.run(
        ["git", "apply", "--allow-empty", pf_path],
        cwd=verify_repo, capture_output=True, text=True
    )
    if result.returncode == 0:
        applied += 1
        os.unlink(pf_path)
        continue

    # Fallback: patch -p1 --fuzz=3
    result = subprocess.run(
        ["patch", "-p1", "--fuzz=3", "-i", pf_path],
        cwd=verify_repo, capture_output=True, text=True
    )
    if result.returncode == 0:
        applied += 1
        os.unlink(pf_path)
        continue

    # Fallback: git apply with 3way
    result = subprocess.run(
        ["git", "apply", "--allow-empty", "--3way", pf_path],
        cwd=verify_repo, capture_output=True, text=True
    )
    if result.returncode == 0:
        applied += 1
        os.unlink(pf_path)
        continue

    failed += 1
    file_name = entry.get("file", "unknown")
    print(f"[artifact_verifier] Patch for {file_name} failed to apply", file=sys.stderr)
    os.unlink(pf_path)

print(f"[artifact_verifier] Patches applied: {applied}, failed: {failed}", file=sys.stderr)
print(applied)
PYEOF
}

echo "[artifact_verifier] Helper functions loaded"
