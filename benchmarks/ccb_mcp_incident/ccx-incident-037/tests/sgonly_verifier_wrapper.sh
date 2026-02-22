#!/bin/bash
# SG-only verifier wrapper: restore full repo + overlay agent changes
#
# Source this at the TOP of test.sh for build-requiring tasks that use
# sg_only_env mode. It detects /tmp/.sg_only_mode and:
#   1. Identifies files the agent wrote (non-empty, non-git, non-test)
#   2. Backs up those files to /tmp/agent_work/
#   3. Restores the full repo from /repo_full/
#   4. Overlays agent's changes on top
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

echo "[sg_only_verifier] Detected sg_only mode, restoring full repo..."

# Read the working directory
WORKDIR="$(cat /tmp/.sg_only_workdir 2>/dev/null || echo '/app')"
echo "[sg_only_verifier] Working directory: $WORKDIR"

if [ ! -d /repo_full ]; then
    echo "[sg_only_verifier] WARNING: /repo_full not found, cannot restore"
    return 0 2>/dev/null || exit 0
fi

# 1. Find files the agent wrote (non-empty, non-git, non-test files)
cd "$WORKDIR"
mkdir -p /tmp/agent_work
AGENT_FILES=0
find . -type f -size +0 ! -path './.git/*' ! -path './tests/*' ! -path './.claude/*' \
    -print0 | while IFS= read -r -d '' f; do
    mkdir -p "/tmp/agent_work/$(dirname "$f")"
    cp "$f" "/tmp/agent_work/$f"
    AGENT_FILES=$((AGENT_FILES + 1))
done
echo "[sg_only_verifier] Backed up agent-written files"

# 2. Restore full repo from backup
rsync -a --delete /repo_full/ "$WORKDIR/"
echo "[sg_only_verifier] Restored full repo from /repo_full/"

# 3. Overlay agent's changes
cd /tmp/agent_work
find . -type f -print0 | while IFS= read -r -d '' f; do
    target="${WORKDIR}/${f#./}"
    mkdir -p "$(dirname "$target")"
    cp "$f" "$target"
done
echo "[sg_only_verifier] Overlaid agent changes"

# Return to working directory
cd "$WORKDIR"
echo "[sg_only_verifier] Restore complete, proceeding with tests"
