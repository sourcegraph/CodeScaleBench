#!/bin/bash
# SG-only verifier wrapper: restore full repo + overlay agent changes
#
# Source this at the TOP of test.sh for build-requiring tasks that use
# sg_only_env mode. It detects /tmp/.sg_only_mode and:
#
# PRIMARY PATH (clone manifest):
#   1. Reads clone manifest from /tmp/.sg_only_clone_manifest.json
#   2. Backs up agent-written files (non-empty, non-git, non-test)
#   3. Clones each mirror repo with --depth 1
#   4. Re-runs inject_defects.sh if specified in manifest
#   5. Overlays agent changes on top
#
# LEGACY FALLBACK (pre-v2 images):
#   If manifest is missing but /repo_full/ exists, restores from /repo_full/
#   as before. This ensures unregenerated images still work during rollout.
#
# For non-sg_only runs, this script is a no-op.
#
# Usage in test.sh:
#   #!/bin/bash
#   # Source the sg_only wrapper (no-op if not in sg_only mode)
#   if [ -f /tests/sgonly_verifier_wrapper.sh ]; then
#       source /tests/sgonly_verifier_wrapper.sh
#   fi
#   # ... rest of test.sh as normal ...

if [ ! -f /tmp/.sg_only_mode ]; then
    # Not in sg_only mode — nothing to do
    return 0 2>/dev/null || exit 0
fi

# Idempotency guard: skip if already sourced (avoids double-clone when
# test.sh sources this wrapper and then eval.sh sources it again)
if [ -n "${_SG_ONLY_RESTORED:-}" ]; then
    return 0 2>/dev/null || exit 0
fi
export _SG_ONLY_RESTORED=1

echo "[sg_only_verifier] Detected sg_only mode, restoring full repo..."

# ---------------------------------------------------------------------------
# Helper: back up agent-written files from a directory
# ---------------------------------------------------------------------------
backup_agent_files() {
    local srcdir="$1"
    if [ ! -d "$srcdir" ]; then
        return
    fi
    cd "$srcdir"
    mkdir -p /tmp/agent_work
    find . -type f -size +0 \
        ! -path './.git/*' \
        ! -path './tests/*' \
        ! -path './.claude/*' \
        -print0 | while IFS= read -r -d '' f; do
        mkdir -p "/tmp/agent_work/$(dirname "$f")"
        cp "$f" "/tmp/agent_work/$f"
    done
    echo "[sg_only_verifier] Backed up agent-written files from $srcdir"
}

# ---------------------------------------------------------------------------
# Helper: overlay agent-written files back onto a directory
# ---------------------------------------------------------------------------
overlay_agent_files() {
    local targetdir="$1"
    if [ ! -d /tmp/agent_work ]; then
        return
    fi
    cd /tmp/agent_work
    find . -type f -print0 | while IFS= read -r -d '' f; do
        local target="${targetdir}/${f#./}"
        mkdir -p "$(dirname "$target")"
        cp "$f" "$target"
    done
    echo "[sg_only_verifier] Overlaid agent changes onto $targetdir"
}

# ---------------------------------------------------------------------------
# PRIMARY PATH: clone manifest
# ---------------------------------------------------------------------------
MANIFEST="/tmp/.sg_only_clone_manifest.json"

if [ -f "$MANIFEST" ]; then
    echo "[sg_only_verifier] Found clone manifest, using clone-at-verify strategy"

    # Parse manifest with python3 (always available in our images)
    WORKDIR=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(m.get('workdir', '/workspace'))")
    echo "[sg_only_verifier] Working directory: $WORKDIR"

    # 1. Back up agent-written files
    backup_agent_files "$WORKDIR"

    # 2. Clone each mirror repo
    REPO_COUNT=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(len(m.get('repos', [])))")
    for i in $(seq 0 $((REPO_COUNT - 1))); do
        MIRROR=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(m['repos'][$i]['mirror'])")
        TARGET_DIR=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(m['repos'][$i].get('target_dir', '.'))")
        CLONE_URL="https://github.com/${MIRROR}.git"

        if [ "$TARGET_DIR" = "." ]; then
            CLONE_TARGET="$WORKDIR"
        else
            CLONE_TARGET="${WORKDIR}/${TARGET_DIR}"
        fi

        echo "[sg_only_verifier] Cloning $MIRROR -> $CLONE_TARGET"

        # Remove existing directory contents (truncated files) but preserve .git
        # for target_dir="." we need to be careful with the working directory
        if [ "$TARGET_DIR" = "." ]; then
            # For root workspace: remove everything except .git, then clone into temp and move
            TMPCLONE=$(mktemp -d)
            if git clone --depth 1 "$CLONE_URL" "$TMPCLONE" 2>/dev/null; then
                # Remove old files (except .git and tests)
                find "$CLONE_TARGET" -mindepth 1 -maxdepth 1 \
                    ! -name '.git' ! -name 'tests' ! -name '.claude' \
                    -exec rm -rf {} + 2>/dev/null || true
                # Copy cloned files (except .git)
                cd "$TMPCLONE"
                find . -mindepth 1 -maxdepth 1 ! -name '.git' -exec cp -a {} "$CLONE_TARGET/" \;
                # If workspace has no HEAD (bare git init), use mirror .git
                # so that git diff HEAD works for diff-based verifiers.
                if ! git -C "$CLONE_TARGET" rev-parse HEAD >/dev/null 2>&1; then
                    rm -rf "$CLONE_TARGET/.git"
                    cp -a "$TMPCLONE/.git" "$CLONE_TARGET/.git"
                    echo "[sg_only_verifier] Replaced empty .git with mirror .git for diff baseline"
                fi
                cd /
                rm -rf "$TMPCLONE"
                echo "[sg_only_verifier] Restored $MIRROR to $CLONE_TARGET"
            else
                echo "[sg_only_verifier] WARNING: Failed to clone $CLONE_URL"
                rm -rf "$TMPCLONE"
            fi
        else
            # For subdirectory: remove and re-clone
            rm -rf "$CLONE_TARGET"
            if git clone --depth 1 "$CLONE_URL" "$CLONE_TARGET" 2>/dev/null; then
                echo "[sg_only_verifier] Restored $MIRROR to $CLONE_TARGET"
            else
                echo "[sg_only_verifier] WARNING: Failed to clone $CLONE_URL"
            fi
        fi
    done

    # 3. Re-run inject_defects if specified
    INJECT_SCRIPT=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(m.get('inject_defects', ''))")
    if [ -n "$INJECT_SCRIPT" ] && [ -f "$INJECT_SCRIPT" ]; then
        echo "[sg_only_verifier] Running defect injection: $INJECT_SCRIPT"
        cd "$WORKDIR"
        chmod +x "$INJECT_SCRIPT"
        bash "$INJECT_SCRIPT"
        echo "[sg_only_verifier] Defect injection complete"
    fi

    # 4. Overlay agent changes
    overlay_agent_files "$WORKDIR"

    # Return to working directory
    cd "$WORKDIR"
    echo "[sg_only_verifier] Clone-at-verify restore complete, proceeding with tests"

    return 0 2>/dev/null || exit 0
fi

# ---------------------------------------------------------------------------
# LEGACY FALLBACK: /repo_full/ restore (for pre-v2 images)
# ---------------------------------------------------------------------------
echo "[sg_only_verifier] No clone manifest found, trying legacy /repo_full/ restore..."

# Read the working directory
WORKDIR="$(cat /tmp/.sg_only_workdir 2>/dev/null || echo '/app')"
echo "[sg_only_verifier] Working directory: $WORKDIR"

if [ ! -d /repo_full ]; then
    echo "[sg_only_verifier] WARNING: /repo_full not found, cannot restore"
    return 0 2>/dev/null || exit 0
fi

# 1. Find files the agent wrote (non-empty, non-git, non-test files)
backup_agent_files "$WORKDIR"

# 2. Restore full repo from backup
rsync -a --delete /repo_full/ "$WORKDIR/"
echo "[sg_only_verifier] Restored full repo from /repo_full/"

# 3. Overlay agent's changes
overlay_agent_files "$WORKDIR"

# Return to working directory
cd "$WORKDIR"
echo "[sg_only_verifier] Legacy restore complete, proceeding with tests"
