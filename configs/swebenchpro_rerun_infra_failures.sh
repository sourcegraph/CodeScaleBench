#!/bin/bash
# SWE-bench Pro Infra Failure Re-runs
#
# Re-runs 34 task-config pairs that failed due to:
#   - Rate limiting (0 output tokens, sub-10s agent time)
#   - Node.js crash (protonmail, fixed in US-002)
#   - Missing runs (gap-fill tasks never run with SG_full)
#
# Generated from ralph/swebenchpro_rerun_plan.json
#
# Usage:
#   ./configs/swebenchpro_rerun_infra_failures.sh [OPTIONS]
#
# Options:
#   --baseline-only    Run only baseline reruns
#   --base-only        Run only sourcegraph_base reruns
#   --full-only        Run only sourcegraph_full reruns
#   --dry-run          Print commands without executing
#   --parallel N       Override parallel jobs (default: auto)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

AGENT_DIR="${AGENT_DIR:-$HOME/evals/custom_agents/agents/claudecode}"
export PYTHONPATH="${AGENT_DIR}:$(pwd):$PYTHONPATH"

source "$SCRIPT_DIR/_common.sh"

# Load credentials
if [ -f ~/evals/.env.local ]; then
    echo "Loading credentials from ~/evals/.env.local..."
    source ~/evals/.env.local
fi

enforce_subscription_mode
ensure_fresh_token

# ============================================
# CONFIGURATION
# ============================================
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
MODEL="${MODEL:-anthropic/claude-opus-4-6}"
CONCURRENCY=2
TIMEOUT_MULTIPLIER=10
CATEGORY="${CATEGORY:-official}"
DRY_RUN=false
RUN_BASELINE=true
RUN_BASE=true
RUN_FULL=true
SINGLE_ACCOUNT=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --baseline-only) RUN_BASE=false; RUN_FULL=false; shift ;;
        --base-only) RUN_BASELINE=false; RUN_FULL=false; shift ;;
        --full-only) RUN_BASELINE=false; RUN_BASE=false; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --parallel) PARALLEL_JOBS="$2"; shift 2 ;;
        --model) MODEL="$2"; shift 2 ;;
        --single-account) SINGLE_ACCOUNT=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [ "$SINGLE_ACCOUNT" = true ]; then
    CLAUDE_HOMES=("$HOME")
    PARALLEL_JOBS=${PARALLEL_JOBS:-1}
    echo "Single-account mode (using \$HOME)"
else
    setup_dual_accounts
fi

# Derive model short name
_model_lower=$(echo "$MODEL" | awk -F/ '{print $NF}' | tr '[:upper:]' '[:lower:]')
case "$_model_lower" in
    *opus*)   MODEL_SHORT="opus" ;;
    *sonnet*) MODEL_SHORT="sonnet" ;;
    *haiku*)  MODEL_SHORT="haiku" ;;
    *)        MODEL_SHORT=$(echo "$_model_lower" | tr -d '-' | tr -d '_' | cut -c1-8) ;;
esac

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
JOBS_BASE="runs/${CATEGORY}/swebenchpro_rerun_${MODEL_SHORT}_${TIMESTAMP}"

# ============================================
# SOURCEGRAPH REPO MAPPING (for MCP configs)
# ============================================
declare -A SG_REPO=(
    ["instance_nodebb__nodebb-76c6e30282906ac664f2c9278fc90999b27b1f48-vd59a5728dfc977f44533186ace531248c2917516"]="sg-benchmarks/nodebb--76c6e302"
    ["instance_nodebb__nodebb-eb49a64974ca844bca061744fb3383f5d13b02ad-vnan"]="sg-benchmarks/nodebb--eb49a649"
    ["instance_nodebb__nodebb-f1a80d48cc45877fcbadf34c2345dd9709722c7f-v4fbcfae8b15e4ce5d132c408bca69ebb9cf146ed"]="sg-benchmarks/nodebb--f1a80d48"
    ["instance_ansible__ansible-b2a289dcbb702003377221e25f62c8a3608f0e89-v173091e2e36d38c978002990795f66cfc0af30ad"]="sg-benchmarks/ansible--b2a289dc"
    ["instance_element-hq__element-web-f14374a51c153f64f313243f2df6ea4971db4e15"]="sg-benchmarks/element-web--f14374a5"
    ["instance_flipt-io__flipt-3d5a345f94c2adc8a0eaa102c189c08ad4c0f8e8"]="sg-benchmarks/flipt--3d5a345f"
    ["instance_flipt-io__flipt-9f8127f225a86245fa35dca4885c2daef824ee55"]="sg-benchmarks/flipt--9f8127f2"
    ["instance_flipt-io__flipt-b433bd05ce405837804693bebd5f4b88d87133c8"]="sg-benchmarks/flipt--b433bd05"
    ["instance_flipt-io__flipt-c188284ff0c094a4ee281afebebd849555ebee59"]="sg-benchmarks/flipt--c188284f"
    ["instance_future-architect__vuls-139f3a81b66c47e6d8f70ce6c4afe7a9196a6ea8"]="sg-benchmarks/vuls--139f3a81"
    ["instance_future-architect__vuls-4c04acbd9ea5b073efe999e33381fa9f399d6f27"]="sg-benchmarks/vuls--4c04acbd"
    ["instance_future-architect__vuls-d18e7a751d07260d75ce3ba0cd67c4a6aebfd967"]="sg-benchmarks/vuls--d18e7a75"
    ["instance_gravitational__teleport-0415e422f12454db0c22316cf3eaa5088d6b6322"]="sg-benchmarks/teleport--0415e422"
    ["instance_gravitational__teleport-3587cca7840f636489449113969a5066025dd5bf"]="sg-benchmarks/teleport--3587cca7"
    ["instance_gravitational__teleport-7744f72c6eb631791434b648ba41083b5f6d2278-vce94f93ad1030e3136852817f2423c1b3ac37bc4"]="sg-benchmarks/teleport--7744f72c"
    ["instance_gravitational__teleport-8302d467d160f869b77184e262adbe2fbc95d9ba-vce94f93ad1030e3136852817f2423c1b3ac37bc4"]="sg-benchmarks/teleport--8302d467"
    ["instance_internetarchive__openlibrary-7f6b722a10f822171501d027cad60afe53337732-ve8c8d62a2b60610a3c4631f5f23ed866bada9818"]="sg-benchmarks/openlibrary--7f6b722a"
    ["instance_internetarchive__openlibrary-92db3454aeaa02f89b4cdbc3103f7e95c9759f92-v2c55207218fb8a0138425cbf7d9675272e240b90"]="sg-benchmarks/openlibrary--92db3454"
    ["instance_internetarchive__openlibrary-c506c1b0b678892af5cb22c1c1dbc35d96787a0a-v0f5aece3601a5b4419f7ccec1dbda2071be28ee4"]="sg-benchmarks/openlibrary--c506c1b0"
    ["instance_internetarchive__openlibrary-d109cc7e6e161170391f98f9a6fa1d02534c18e4-ve8c8d62a2b60610a3c4631f5f23ed866bada9818"]="sg-benchmarks/openlibrary--d109cc7e"
    ["instance_navidrome__navidrome-9c3b4561652a15846993d477003e111f0df0c585"]="sg-benchmarks/navidrome--9c3b4561"
    ["instance_navidrome__navidrome-d0dceae0943b8df16e579c2d9437e11760a0626a"]="sg-benchmarks/navidrome--d0dceae0"
    ["instance_protonmail__webclients-369fd37de29c14c690cb3b1c09a949189734026f"]="sg-benchmarks/webclients--369fd37d"
    ["instance_protonmail__webclients-8be4f6cb9380fcd2e67bcb18cef931ae0d4b869c"]="sg-benchmarks/webclients--8be4f6cb"
    ["instance_protonmail__webclients-c6f65d205c401350a226bb005f42fac1754b0b5b"]="sg-benchmarks/webclients--c6f65d20"
    ["instance_protonmail__webclients-caf10ba9ab2677761c88522d1ba8ad025779c492"]="sg-benchmarks/webclients--caf10ba9"
    ["instance_qutebrowser__qutebrowser-233cb1cc48635130e5602549856a6fa4ab4c087f-v35616345bb8052ea303186706cec663146f0f184"]="sg-benchmarks/qutebrowser--233cb1cc"
    ["instance_qutebrowser__qutebrowser-394bfaed6544c952c6b3463751abab3176ad4997-vafb3e8e01b31319c66c4e666b8a3b1d8ba55db24"]="sg-benchmarks/qutebrowser--394bfaed"
    ["instance_qutebrowser__qutebrowser-3fd8e12949b8feda401930574facf09dd4180bba"]="sg-benchmarks/qutebrowser--3fd8e129"
    ["instance_qutebrowser__qutebrowser-e5340c449f23608803c286da0563b62f58ba25b0-v059c6fdc75567943479b23ebca7c07b5e9a7f34c"]="sg-benchmarks/qutebrowser--e5340c44"
    ["instance_tutao__tutanota-f373ac3808deefce8183dad8d16729839cc330c1-v2939aa9f4356f0dc9f523ee5ce19d09e08ab979b"]="sg-benchmarks/tutanota--f373ac38"
    ["instance_element-hq__element-web-cf3c899dd1f221aa1a1f4c5a80dffc05b9c21c85-vnan"]="sg-benchmarks/element-web--cf3c899d"
)

# ============================================
# GAP-FILL TASKS (need --path mode, not --dataset)
# These are NOT in harbor's swebenchpro registry.
# ============================================
# Task ID hashes that require --path mode
GAP_FILL_HASHES="0415e422 eb49a649 f373ac38 76c6e302 f1a80d48 b2a289dc 139f3a81 c1b1c6a1 eea46a0d 1832b4ee f3ffe17a"

is_gap_fill() {
    local task_id=$1
    for hash in $GAP_FILL_HASHES; do
        if [[ "$task_id" == *"$hash"* ]]; then
            return 0
        fi
    done
    return 1
}

# Map task_id to local --path directory
# Harbor uses double-underscores in task_id but single-dash in dir names
task_to_path() {
    local task_id=$1
    # Convert instance_org__repo-hash to the directory name format
    local dir_name
    dir_name=$(echo "$task_id" | sed 's/__/-/')
    local task_dir="benchmarks/ccb_swebenchpro/tasks/${dir_name}"
    if [ -d "$task_dir" ]; then
        echo "$task_dir"
    else
        echo ""
    fi
}

# ============================================
# TASK LISTS (from swebenchpro_rerun_plan.json)
# ============================================

# Baseline: 13 reruns (all --dataset except tutanota)
BASELINE_TASKS=(
    "instance_future-architect__vuls-d18e7a751d07260d75ce3ba0cd67c4a6aebfd967"
    "instance_gravitational__teleport-3587cca7840f636489449113969a5066025dd5bf"
    "instance_gravitational__teleport-7744f72c6eb631791434b648ba41083b5f6d2278-vce94f93ad1030e3136852817f2423c1b3ac37bc4"
    "instance_gravitational__teleport-8302d467d160f869b77184e262adbe2fbc95d9ba-vce94f93ad1030e3136852817f2423c1b3ac37bc4"
    "instance_internetarchive__openlibrary-92db3454aeaa02f89b4cdbc3103f7e95c9759f92-v2c55207218fb8a0138425cbf7d9675272e240b90"
    "instance_protonmail__webclients-369fd37de29c14c690cb3b1c09a949189734026f"
    "instance_protonmail__webclients-8be4f6cb9380fcd2e67bcb18cef931ae0d4b869c"
    "instance_protonmail__webclients-c6f65d205c401350a226bb005f42fac1754b0b5b"
    "instance_protonmail__webclients-caf10ba9ab2677761c88522d1ba8ad025779c492"
    "instance_qutebrowser__qutebrowser-233cb1cc48635130e5602549856a6fa4ab4c087f-v35616345bb8052ea303186706cec663146f0f184"
    "instance_qutebrowser__qutebrowser-394bfaed6544c952c6b3463751abab3176ad4997-vafb3e8e01b31319c66c4e666b8a3b1d8ba55db24"
    "instance_qutebrowser__qutebrowser-3fd8e12949b8feda401930574facf09dd4180bba"
    "instance_tutao__tutanota-f373ac3808deefce8183dad8d16729839cc330c1-v2939aa9f4356f0dc9f523ee5ce19d09e08ab979b"
)

# SG_base: 16 reruns
SGBASE_TASKS=(
    "instance_nodebb__nodebb-eb49a64974ca844bca061744fb3383f5d13b02ad-vnan"
    "instance_element-hq__element-web-f14374a51c153f64f313243f2df6ea4971db4e15"
    "instance_future-architect__vuls-4c04acbd9ea5b073efe999e33381fa9f399d6f27"
    "instance_future-architect__vuls-d18e7a751d07260d75ce3ba0cd67c4a6aebfd967"
    "instance_gravitational__teleport-0415e422f12454db0c22316cf3eaa5088d6b6322"
    "instance_gravitational__teleport-3587cca7840f636489449113969a5066025dd5bf"
    "instance_gravitational__teleport-7744f72c6eb631791434b648ba41083b5f6d2278-vce94f93ad1030e3136852817f2423c1b3ac37bc4"
    "instance_internetarchive__openlibrary-92db3454aeaa02f89b4cdbc3103f7e95c9759f92-v2c55207218fb8a0138425cbf7d9675272e240b90"
    "instance_protonmail__webclients-369fd37de29c14c690cb3b1c09a949189734026f"
    "instance_protonmail__webclients-8be4f6cb9380fcd2e67bcb18cef931ae0d4b869c"
    "instance_protonmail__webclients-c6f65d205c401350a226bb005f42fac1754b0b5b"
    "instance_protonmail__webclients-caf10ba9ab2677761c88522d1ba8ad025779c492"
    "instance_qutebrowser__qutebrowser-394bfaed6544c952c6b3463751abab3176ad4997-vafb3e8e01b31319c66c4e666b8a3b1d8ba55db24"
    "instance_qutebrowser__qutebrowser-3fd8e12949b8feda401930574facf09dd4180bba"
    "instance_qutebrowser__qutebrowser-e5340c449f23608803c286da0563b62f58ba25b0-v059c6fdc75567943479b23ebca7c07b5e9a7f34c"
    "instance_tutao__tutanota-f373ac3808deefce8183dad8d16729839cc330c1-v2939aa9f4356f0dc9f523ee5ce19d09e08ab979b"
)

# SG_full: 5 reruns (all protonmail)
SGFULL_TASKS=(
    "instance_internetarchive__openlibrary-92db3454aeaa02f89b4cdbc3103f7e95c9759f92-v2c55207218fb8a0138425cbf7d9675272e240b90"
    "instance_protonmail__webclients-369fd37de29c14c690cb3b1c09a949189734026f"
    "instance_protonmail__webclients-8be4f6cb9380fcd2e67bcb18cef931ae0d4b869c"
    "instance_protonmail__webclients-c6f65d205c401350a226bb005f42fac1754b0b5b"
    "instance_protonmail__webclients-caf10ba9ab2677761c88522d1ba8ad025779c492"
)

echo "=============================================="
echo "SWE-bench Pro Infra Failure Re-runs"
echo "=============================================="
echo "Model: ${MODEL}"
echo "Dry run: ${DRY_RUN}"
echo "Parallel jobs: ${PARALLEL_JOBS}"
echo "Jobs directory: ${JOBS_BASE}"
echo ""
echo "Re-run counts:"
echo "  Baseline:         ${#BASELINE_TASKS[@]}"
echo "  Sourcegraph Base: ${#SGBASE_TASKS[@]}"
echo "  Sourcegraph Full: ${#SGFULL_TASKS[@]}"
echo "  Total:            $(( ${#BASELINE_TASKS[@]} + ${#SGBASE_TASKS[@]} + ${#SGFULL_TASKS[@]} ))"
echo ""

mkdir -p "${JOBS_BASE}"

# ============================================
# HELPER: Run a single task (handles --path vs --dataset)
# ============================================
run_single_task() {
    local task_id=$1
    local config=$2          # baseline, sourcegraph_base, sourcegraph_full
    local mcp_type=$3        # none, sourcegraph_base, sourcegraph_full
    local jobs_subdir="${JOBS_BASE}/${config}"

    mkdir -p "$jobs_subdir"

    # Set SG repo for MCP configs
    if [ "$mcp_type" != "none" ]; then
        local sg_repo="${SG_REPO[$task_id]:-}"
        if [ -n "$sg_repo" ]; then
            export SOURCEGRAPH_REPO_NAME="$sg_repo"
            echo "    SOURCEGRAPH_REPO_NAME=${sg_repo}"
        else
            unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
            echo "    No SG repo mapping"
        fi
    fi

    # Determine --path vs --dataset mode
    local harbor_args=""
    if is_gap_fill "$task_id"; then
        local task_path
        task_path=$(task_to_path "$task_id")
        if [ -z "$task_path" ]; then
            echo "    ERROR: Cannot find local task directory for gap-fill task $task_id"
            return 1
        fi
        harbor_args="--path $task_path"
        echo "    Mode: --path ($task_path)"
    else
        harbor_args="--dataset swebenchpro -t $task_id"
        echo "    Mode: --dataset swebenchpro"
    fi

    if [ "$DRY_RUN" = true ]; then
        echo "    [DRY RUN] BASELINE_MCP_TYPE=$mcp_type harbor run $harbor_args --agent-import-path $AGENT_PATH --model $MODEL --jobs-dir $jobs_subdir -n $CONCURRENCY --timeout-multiplier $TIMEOUT_MULTIPLIER"
        return 0
    fi

    BASELINE_MCP_TYPE=$mcp_type harbor run \
        $harbor_args \
        --agent-import-path "$AGENT_PATH" \
        --model "$MODEL" \
        --jobs-dir "$jobs_subdir" \
        -n $CONCURRENCY \
        --timeout-multiplier $TIMEOUT_MULTIPLIER \
        2>&1 | tee "${jobs_subdir}/${task_id}.log" || true
}

# ============================================
# RUN BASELINE RERUNS
# ============================================
if [ "$RUN_BASELINE" = true ] && [ ${#BASELINE_TASKS[@]} -gt 0 ]; then
    echo ""
    echo "[BASELINE] Re-running ${#BASELINE_TASKS[@]} infra-failed tasks..."
    echo ""
    ensure_fresh_token_all

    for task_id in "${BASELINE_TASKS[@]}"; do
        echo "  [$((++_bl_count))/${#BASELINE_TASKS[@]}] ${task_id}"
        run_single_task "$task_id" "baseline" "none"
        echo ""
    done

    validate_and_report "${JOBS_BASE}/baseline" "baseline"
fi

# ============================================
# RUN SOURCEGRAPH_BASE RERUNS
# ============================================
if [ "$RUN_BASE" = true ] && [ ${#SGBASE_TASKS[@]} -gt 0 ]; then
    echo ""
    echo "[SG_BASE] Re-running ${#SGBASE_TASKS[@]} infra-failed tasks..."
    echo ""
    ensure_fresh_token_all

    for task_id in "${SGBASE_TASKS[@]}"; do
        echo "  [$((++_sb_count))/${#SGBASE_TASKS[@]}] ${task_id}"
        run_single_task "$task_id" "sourcegraph_base" "sourcegraph_base"
        echo ""
    done

    validate_and_report "${JOBS_BASE}/sourcegraph_base" "sourcegraph_base"
fi

# ============================================
# RUN SOURCEGRAPH_FULL RERUNS
# ============================================
if [ "$RUN_FULL" = true ] && [ ${#SGFULL_TASKS[@]} -gt 0 ]; then
    echo ""
    echo "[SG_FULL] Re-running ${#SGFULL_TASKS[@]} infra-failed tasks..."
    echo ""
    ensure_fresh_token_all

    for task_id in "${SGFULL_TASKS[@]}"; do
        echo "  [$((++_sf_count))/${#SGFULL_TASKS[@]}] ${task_id}"
        run_single_task "$task_id" "sourcegraph_full" "sourcegraph_full"
        echo ""
    done

    validate_and_report "${JOBS_BASE}/sourcegraph_full" "sourcegraph_full"
fi

print_validation_summary "$JOBS_BASE"

echo ""
echo "=============================================="
echo "Re-runs Complete!"
echo "=============================================="
echo "Results saved to: ${JOBS_BASE}"
echo ""
echo "Next steps:"
echo "  1. Verify results: python3 scripts/generate_manifest.py"
echo "  2. Check for remaining gaps: python3 -c \"import json; m=json.load(open('runs/official/MANIFEST.json')); print(len([t for t in m['tasks'] if t['reward']==0]))\""
echo ""
