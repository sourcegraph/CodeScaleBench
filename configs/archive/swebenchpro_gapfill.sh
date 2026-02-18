#!/bin/bash
# SWE-bench Pro Gap-Fill: Run the 7 missing tasks across all 3 configs.
# One-shot script — delete after gap-fill is complete.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

AGENT_DIR="${AGENT_DIR:-$HOME/evals/custom_agents/agents/claudecode}"
export PYTHONPATH="${AGENT_DIR}:$(pwd):$PYTHONPATH"

source "$SCRIPT_DIR/_common.sh"

if [ -f ~/evals/.env.local ]; then
    source ~/evals/.env.local
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: ANTHROPIC_API_KEY is not set"; exit 1
fi

ensure_fresh_token

# ============================================
# CONFIGURATION
# ============================================
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
MODEL="${MODEL:-anthropic/claude-opus-4-6}"
CONCURRENCY=2
TIMEOUT_MULTIPLIER=10
CATEGORY="${CATEGORY:-staging}"
RUN_BASELINE=true
RUN_BASE=true
RUN_FULL=true

while [[ $# -gt 0 ]]; do
    case $1 in
        --baseline-only) RUN_BASE=false; RUN_FULL=false; shift ;;
        --base-only) RUN_BASELINE=false; RUN_FULL=false; shift ;;
        --full-only) RUN_BASELINE=false; RUN_BASE=false; shift ;;
        --parallel) PARALLEL_JOBS="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

setup_multi_accounts

if { [ "$RUN_BASE" = true ] || [ "$RUN_FULL" = true ]; } && [ -z "$SOURCEGRAPH_ACCESS_TOKEN" ]; then
    echo "WARNING: SOURCEGRAPH_ACCESS_TOKEN not set — skipping MCP modes"
    RUN_BASE=false; RUN_FULL=false
fi

# ============================================
# GAP-FILL: 6 missing tasks (1 excluded: nodebb-eb49a649 has no Docker image)
# ============================================
# These tasks are NOT in harbor's swebenchpro dataset registry, so we use --path mode
# with local task directories instead of --dataset swebenchpro -t
TASKS_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks/ccb_swebenchpro/tasks"
TASK_IDS=(
    "instance_nodebb-nodebb-76c6e30282906ac664f2c9278fc90999b27b1f48-vd59a5728dfc977f44533186ace531248c2917516"
    # EXCLUDED: eb49a649 — base image jefzda/sweap-images:...eb49a649...-vnan not published to Docker Hub
    "instance_nodebb-nodebb-f1a80d48cc45877fcbadf34c2345dd9709722c7f-v4fbcfae8b15e4ce5d132c408bca69ebb9cf146ed"
    "instance_ansible-ansible-eea46a0d1b99a6dadedbb6a3502d599235fa7ec3-v390e508d27db7a51eece36bb6d9698b63a5b638a"
    "instance_future-architect-vuls-1832b4ee3a20177ad313d806983127cb6e53f5cf"
    "instance_gravitational-teleport-c1b1c6a1541c478d7777a48fca993cc8206c73b9"
    "instance_tutao-tutanota-f3ffe17af6e8ab007e8d461355057ad237846d9d-vbc0d9ba8f0071fbe982809910959a6ff8884dbbf"
)

# Sourcegraph repo name mapping (for MCP modes)
# Only NodeBB repos are SG-indexed; other 4 gap-fill tasks have no indexed repos
# Keys use hyphenated directory names (matching TASK_IDS above)
declare -A SWEBENCHPRO_SG=(
    ["instance_nodebb-nodebb-76c6e30282906ac664f2c9278fc90999b27b1f48-vd59a5728dfc977f44533186ace531248c2917516"]="sg-benchmarks/nodebb--76c6e302"
    ["instance_nodebb-nodebb-eb49a64974ca844bca061744fb3383f5d13b02ad-vnan"]="sg-benchmarks/nodebb--eb49a649"
    ["instance_nodebb-nodebb-f1a80d48cc45877fcbadf34c2345dd9709722c7f-v4fbcfae8b15e4ce5d132c408bca69ebb9cf146ed"]="sg-benchmarks/nodebb--f1a80d48"
)

SELECTION_FILE="$SCRIPT_DIR/selected_benchmark_tasks.json"

_model_lower=$(echo "$MODEL" | awk -F/ '{print $NF}' | tr '[:upper:]' '[:lower:]')
case "$_model_lower" in
    *opus*)   MODEL_SHORT="opus" ;;
    *sonnet*) MODEL_SHORT="sonnet" ;;
    *) MODEL_SHORT=$(echo "$_model_lower" | tr -d '-' | cut -c1-8) ;;
esac

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
JOBS_BASE="runs/${CATEGORY}/swebenchpro_gapfill_${MODEL_SHORT}_${TIMESTAMP}"

echo "=============================================="
echo "SWE-bench Pro GAP-FILL (6 missing tasks)"
echo "=============================================="
echo "Model: ${MODEL}"
echo "Tasks: ${#TASK_IDS[@]}"
echo "Parallel jobs: ${PARALLEL_JOBS}"
echo "Jobs directory: ${JOBS_BASE}"
echo "Run baseline: ${RUN_BASELINE}"
echo "Run MCP-Base: ${RUN_BASE}"
echo "Run MCP-Full: ${RUN_FULL}"
echo ""

mkdir -p "${JOBS_BASE}"

log_section() { echo ""; echo "========================================"; echo "$1"; echo "========================================"; echo ""; }

extract_all_metrics() {
    local jobs_dir=$1 benchmark=$2 config=$3
    for result_dir in "$jobs_dir"/*/*/; do
        if [ -f "$result_dir/result.json" ] && [ ! -f "$result_dir/task_metrics.json" ]; then
            python3 "$SCRIPT_DIR/../scripts/extract_task_metrics.py" \
                --task-dir "$result_dir" --benchmark "$benchmark" --config "$config" \
                --selected-tasks "$SELECTION_FILE" 2>&1 || true
        fi
    done
}

run_task_batch() {
    local mode=$1 mcp_type=$2
    local jobs_subdir="${JOBS_BASE}/${mode}"
    ensure_fresh_token_all
    mkdir -p "$jobs_subdir"

    _gapfill_run_single() {
        local task_id=$1 task_home=$2
        local task_path="${TASKS_DIR}/${task_id}"

        if [ ! -d "$task_path" ]; then
            echo "ERROR: Task directory not found: $task_path"
            return 1
        fi

        local sg_repo="${SWEBENCHPRO_SG[$task_id]:-}"
        if [ -n "$sg_repo" ]; then
            export SOURCEGRAPH_REPO_NAME="$sg_repo"
        else
            unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
        fi
        echo "  [${mode}] Task ${task_id} [HOME=$task_home]"
        BASELINE_MCP_TYPE=$mcp_type harbor run \
            --path "$task_path" \
            --agent-import-path "$AGENT_PATH" \
            --model "$MODEL" \
            --jobs-dir "$jobs_subdir" \
            -n $CONCURRENCY \
            --timeout-multiplier $TIMEOUT_MULTIPLIER \
            2>&1 | tee "${jobs_subdir}/${task_id}.log" || true
    }

    run_tasks_parallel TASK_IDS _gapfill_run_single || true
    extract_all_metrics "$jobs_subdir" "ccb_swebenchpro" "$mode"
    validate_and_report "$jobs_subdir" "$mode"
}

# ============================================
# MAIN EXECUTION
# ============================================
if [ "$RUN_BASELINE" = true ]; then
    log_section "Gap-Fill: baseline"
    run_task_batch "baseline" "none"
fi

if [ "$RUN_BASE" = true ]; then
    log_section "Gap-Fill: sourcegraph_base"
    run_task_batch "sourcegraph_base" "sourcegraph_base"
fi

if [ "$RUN_FULL" = true ]; then
    log_section "Gap-Fill: sourcegraph_full"
    run_task_batch "sourcegraph_full" "sourcegraph_full"
fi

print_validation_summary "$JOBS_BASE"

echo ""
echo "=============================================="
echo "Gap-Fill Complete!"
echo "=============================================="
echo "Results saved to: ${JOBS_BASE}"
echo "Next: python3 scripts/generate_manifest.py"
