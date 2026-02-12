#!/bin/bash
# SWE-bench Pro 2-Config Comparison Script
#
# Runs selected SWE-bench Pro instances (from selected_benchmark_tasks.json) across 2 configurations:
#   1. Baseline (no MCP)
#   2. MCP-Full (Sourcegraph + Deep Search hybrid)
#
# Usage:
#   ./configs/swebenchpro_3config.sh [OPTIONS]
#
# Options:
#   --baseline-only        Run only baseline (no MCP)
#   --full-only            Run only MCP-Full (sourcegraph_full)
#   --model MODEL          Override model (default: claude-opus-4-6)
#   --concurrency N        Number of concurrent tasks (default: 2)
#   --category CATEGORY    Run category (default: official)
#   --parallel N           Number of parallel task subshells (default: 1)
#
# Prerequisites:
#   - ~/evals/.env.local with USE_SUBSCRIPTION=true (default: 2-account Max subscription)
#   - SOURCEGRAPH_ACCESS_TOKEN in .env.local (required for MCP modes)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# Agent module lives in the evals repo; add it to PYTHONPATH
AGENT_DIR="${AGENT_DIR:-$HOME/evals/custom_agents/agents/claudecode}"
export PYTHONPATH="${AGENT_DIR}:$(pwd):$PYTHONPATH"

# Shared config: subscription mode + token refresh
source "$SCRIPT_DIR/_common.sh"

# ============================================
# LOAD CREDENTIALS
# ============================================
if [ -f ~/evals/.env.local ]; then
    echo "Loading credentials from ~/evals/.env.local..."
    source ~/evals/.env.local
else
    echo "Warning: ~/evals/.env.local not found"
    echo ""
fi

# Verify auth mode (subscription-only)
enforce_subscription_mode
if [ -n "$SOURCEGRAPH_ACCESS_TOKEN" ]; then
    echo "SOURCEGRAPH_ACCESS_TOKEN: set (${#SOURCEGRAPH_ACCESS_TOKEN} chars)"
else
    echo "SOURCEGRAPH_ACCESS_TOKEN: not set"
fi
echo ""

ensure_fresh_token

# ============================================
# CONFIGURATION
# ============================================
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
MODEL="${MODEL:-anthropic/claude-opus-4-6}"
CONCURRENCY=2
TIMEOUT_MULTIPLIER=10
RUN_BASELINE=true
RUN_FULL=true
CATEGORY="${CATEGORY:-official}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --baseline-only)
            RUN_FULL=false
            shift
            ;;
        --full-only)
            RUN_BASELINE=false
            shift
            ;;
        --model)
            MODEL="$2"
            shift 2
            ;;
        --concurrency)
            CONCURRENCY="$2"
            shift 2
            ;;
        --category)
            CATEGORY="$2"
            shift 2
            ;;
        --parallel)
            PARALLEL_JOBS="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Set up dual-account support (auto-detects second account)
setup_dual_accounts

# Check MCP credentials if MCP modes requested

# Load task IDs from canonical selection file
SELECTION_FILE="$SCRIPT_DIR/selected_benchmark_tasks.json"
if [ ! -f "$SELECTION_FILE" ]; then
    echo "ERROR: selected_benchmark_tasks.json not found at $SELECTION_FILE"
    echo "Run: python3 scripts/select_benchmark_tasks.py"
    exit 1
fi

readarray -t TASK_IDS < <(python3 -c "
import json
tasks = json.load(open('$SELECTION_FILE'))['tasks']
for t in tasks:
    if t['benchmark'] == 'ccb_swebenchpro':
        print(t['task_id'])
")

# Derive short model name for run directory (matches V2 id_generator convention)
_model_lower=$(echo "$MODEL" | awk -F/ '{print $NF}' | tr '[:upper:]' '[:lower:]')
case "$_model_lower" in
    *opus*)   MODEL_SHORT="opus" ;;
    *sonnet*) MODEL_SHORT="sonnet" ;;
    *haiku*)  MODEL_SHORT="haiku" ;;
    *gpt-4o*|*gpt4o*) MODEL_SHORT="gpt4o" ;;
    *gpt-4*|*gpt4*)   MODEL_SHORT="gpt4" ;;
    *)        MODEL_SHORT=$(echo "$_model_lower" | tr -d '-' | tr -d '_' | cut -c1-8) ;;
esac

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
JOBS_BASE="runs/${CATEGORY}/swebenchpro_selected_${MODEL_SHORT}_${TIMESTAMP}"

echo "=============================================="
echo "SWE-bench Pro 2-Config Benchmark"
echo "=============================================="
echo "Model: ${MODEL}"
echo "Tasks: ${#TASK_IDS[@]}"
echo "Concurrency: ${CONCURRENCY}"
echo "Parallel jobs: ${PARALLEL_JOBS}"
echo "Timeout multiplier: ${TIMEOUT_MULTIPLIER}x"
echo "Jobs directory: ${JOBS_BASE}"
echo "Run baseline: ${RUN_BASELINE}"
echo "Run MCP-Full: ${RUN_FULL}"
echo ""

# Create jobs directory
mkdir -p "${JOBS_BASE}"

# Build task name arguments
TASK_NAME_ARGS=""
for task_id in "${TASK_IDS[@]}"; do
    TASK_NAME_ARGS="${TASK_NAME_ARGS} -t ${task_id}"
done

# ============================================
# HELPER FUNCTIONS
# ============================================
# Extract per-task metrics for Dashboard
extract_all_metrics() {
    local jobs_dir=$1
    local benchmark=$2
    local config=$3
    echo "Extracting per-task metrics from $jobs_dir..."
    for result_dir in "$jobs_dir"/*/*/; do
        if [ -f "$result_dir/result.json" ] && [ ! -f "$result_dir/task_metrics.json" ]; then
            python3 "$SCRIPT_DIR/../scripts/extract_task_metrics.py" \
                --task-dir "$result_dir" \
                --benchmark "$benchmark" \
                --config "$config" \
                --selected-tasks "$SELECTION_FILE" \
                2>&1 || echo "  WARNING: metrics extraction failed for $(basename $result_dir)"
        fi
    done
}

# Hardcoded SOURCEGRAPH_REPO_NAME mapping for all 36 selected SWE-bench Pro tasks.
# Generated from configs/sg_indexing_list.json — matches sg-benchmarks naming convention.
declare -A SWEBENCHPRO_SG=(
    ["instance_nodebb__nodebb-76c6e30282906ac664f2c9278fc90999b27b1f48-vd59a5728dfc977f44533186ace531248c2917516"]="sg-benchmarks/nodebb--76c6e302"
    ["instance_nodebb__nodebb-eb49a64974ca844bca061744fb3383f5d13b02ad-vnan"]="sg-benchmarks/nodebb--eb49a649"
    ["instance_nodebb__nodebb-f1a80d48cc45877fcbadf34c2345dd9709722c7f-v4fbcfae8b15e4ce5d132c408bca69ebb9cf146ed"]="sg-benchmarks/nodebb--f1a80d48"
    ["instance_ansible__ansible-379058e10f3dbc0fdcaf80394bd09b18927e7d33-v1055803c3a812189a1133297f7f5468579283f86"]="sg-benchmarks/ansible--379058e1"
    ["instance_ansible__ansible-4c5ce5a1a9e79a845aff4978cfeb72a0d4ecf7d6-v1055803c3a812189a1133297f7f5468579283f86"]="sg-benchmarks/ansible--4c5ce5a1"
    ["instance_ansible__ansible-811093f0225caa4dd33890933150a81c6a6d5226-v1055803c3a812189a1133297f7f5468579283f86"]="sg-benchmarks/ansible--811093f0"
    ["instance_ansible__ansible-b2a289dcbb702003377221e25f62c8a3608f0e89-v173091e2e36d38c978002990795f66cfc0af30ad"]="sg-benchmarks/ansible--b2a289dc"
    ["instance_ansible__ansible-e40889e7112ae00a21a2c74312b330e67a766cc0-v1055803c3a812189a1133297f7f5468579283f86"]="sg-benchmarks/ansible--e40889e7"
    ["instance_element-hq__element-web-cf3c899dd1f221aa1a1f4c5a80dffc05b9c21c85-vnan"]="sg-benchmarks/element-web--cf3c899d"
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
)

# Run MCP mode tasks with parallel support; SOURCEGRAPH_REPO_NAME set per task
run_swebench_mcp_task_batch() {
    local mode=$1
    local mcp_type=$2
    local jobs_subdir="${JOBS_BASE}/${mode}"
    ensure_fresh_token_all
    mkdir -p "$jobs_subdir"

    _swebench_run_single() {
        local task_id=$1
        local task_home=$2

        local sg_repo="${SWEBENCHPRO_SG[$task_id]:-}"
        if [ -n "$sg_repo" ]; then
            export SOURCEGRAPH_REPO_NAME="$sg_repo"
            echo "  [${mode}] Task ${task_id} -> SOURCEGRAPH_REPO_NAME=${sg_repo} [HOME=$task_home]"
        else
            unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
            echo "  [${mode}] Task ${task_id} -> no SG repo mapping [HOME=$task_home]"
        fi
        BASELINE_MCP_TYPE=$mcp_type harbor run \
            --dataset swebenchpro \
            -t "$task_id" \
            --agent-import-path "$AGENT_PATH" \
            --model "$MODEL" \
            --jobs-dir "$jobs_subdir" \
            -n $CONCURRENCY \
            --timeout-multiplier $TIMEOUT_MULTIPLIER \
            2>&1 | tee "${jobs_subdir}/${task_id}.log" || true
    }

    run_canary_then_batch TASK_IDS _swebench_run_single "$jobs_subdir" "$mode"

    extract_all_metrics "$jobs_subdir" "ccb_swebenchpro" "$mode"
    validate_and_report "$jobs_subdir" "$mode"
}

# ============================================
# RUN BASELINE (no MCP)
# ============================================
if [ "$RUN_BASELINE" = true ]; then
    echo ""
    echo "[BASELINE] Starting selected-task baseline run..."
    echo ""

    BASELINE_MCP_TYPE=none harbor run \
        --dataset swebenchpro \
        ${TASK_NAME_ARGS} \
        --agent-import-path "${AGENT_PATH}" \
        --model "${MODEL}" \
        --jobs-dir "${JOBS_BASE}/baseline" \
        -n ${CONCURRENCY} \
        --timeout-multiplier ${TIMEOUT_MULTIPLIER} \
        2>&1 | tee "${JOBS_BASE}/baseline.log"

    extract_all_metrics "${JOBS_BASE}/baseline" "ccb_swebenchpro" "baseline"
    validate_and_report "${JOBS_BASE}/baseline" "baseline"
fi

# ============================================
# RUN MCP-Full (sourcegraph_full)
# Per-task iteration to set SOURCEGRAPH_REPO_NAME for indexed repos
# ============================================
if [ "$RUN_FULL" = true ]; then
    echo ""
    echo "[MCP-Full] Starting per-task MCP-Full run..."
    echo ""

    run_swebench_mcp_task_batch "sourcegraph_full" "sourcegraph_full"
fi

print_validation_summary "$JOBS_BASE"

echo ""
echo "=============================================="
echo "Benchmark Complete!"
echo "=============================================="
echo "Results saved to: ${JOBS_BASE}"
echo ""
echo "View results:"
if [ "$RUN_BASELINE" = true ]; then
    echo "  # Baseline - count resolved"
    echo "  cat ${JOBS_BASE}/baseline/*/result.json | jq -s '[.[] | select(.trials[].verifier_result.resolved == true)] | length'"
    echo ""
fi
if [ "$RUN_FULL" = true ]; then
    echo "  # MCP-Full - count resolved"
    echo "  cat ${JOBS_BASE}/sourcegraph_full/*/result.json | jq -s '[.[] | select(.trials[].verifier_result.resolved == true)] | length'"
fi
