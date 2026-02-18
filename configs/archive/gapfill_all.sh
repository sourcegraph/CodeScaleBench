#!/bin/bash
# Gap-Fill: Run all missing tasks identified in coverage audit (2026-02-05).
#
# Covers:
#   1. PyTorch: sgt-007, sgt-017, sgt-024 × all 3 configs = 9 runs
#              sgt-001, sgt-002 × SG_base only = 2 runs (rerun, token_refresh_403)
#   2. SWE-bench Pro SG_full: ansible-eea46a0d, tutanota-f3ffe17a = 2 runs
#
# Total: 13 task runs
#
# NOT included (blocked):
#   - TAC: tac-copilot-arena-endpoint, tac-troubleshoot-dev-setup (copilot-arena-server missing from GitLab)
#   - SWE-bench Pro: nodebb-eb49a649 (Docker image not published)
#
# Usage:
#   ./configs/gapfill_all.sh [--parallel N] [--pytorch-only] [--swebenchpro-only]

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
SELECTION_FILE="$SCRIPT_DIR/selected_benchmark_tasks.json"

RUN_PYTORCH=true
RUN_SWEBENCHPRO=true

while [[ $# -gt 0 ]]; do
    case $1 in
        --pytorch-only) RUN_SWEBENCHPRO=false; shift ;;
        --swebenchpro-only) RUN_PYTORCH=false; shift ;;
        --parallel) PARALLEL_JOBS="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

setup_multi_accounts

if [ -z "$SOURCEGRAPH_ACCESS_TOKEN" ]; then
    echo "WARNING: SOURCEGRAPH_ACCESS_TOKEN not set — MCP modes will run without repo context"
fi

# Derive model short name
_model_lower=$(echo "$MODEL" | awk -F/ '{print $NF}' | tr '[:upper:]' '[:lower:]')
case "$_model_lower" in
    *opus*)   MODEL_SHORT="opus" ;;
    *sonnet*) MODEL_SHORT="sonnet" ;;
    *) MODEL_SHORT=$(echo "$_model_lower" | tr -d '-' | cut -c1-8) ;;
esac

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

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

# ============================================
# PYTORCH GAP-FILL
# ============================================
if [ "$RUN_PYTORCH" = true ]; then
    PYTORCH_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks/ccb_pytorch"
    PYTORCH_JOBS="runs/${CATEGORY}/pytorch_gapfill_${MODEL_SHORT}_${TIMESTAMP}"

    # SG repo mappings for pytorch tasks
    declare -A PYTORCH_SG=(
        ["sgt-001"]="sg-benchmarks/pytorch--ca246612"
        ["sgt-002"]="sg-benchmarks/pytorch--ca246612"
        # sgt-007: commit a61b434d — no SG repo indexed for this commit
        ["sgt-017"]="sg-benchmarks/pytorch--cbe1a35d"
        ["sgt-024"]="sg-benchmarks/pytorch--cbe1a35d"
    )

    _pytorch_run_single() {
        local task_id=$1 task_home=$2
        local task_path="${PYTORCH_DIR}/${task_id}"

        if [ ! -d "$task_path" ]; then
            echo "ERROR: Task directory not found: $task_path"
            return 1
        fi

        local sg_repo="${PYTORCH_SG[$task_id]:-}"
        if [ -n "$sg_repo" ]; then
            export SOURCEGRAPH_REPO_NAME="$sg_repo"
        else
            unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
        fi

        echo "  [pytorch/$_current_config] Task ${task_id} [HOME=$task_home]"
        BASELINE_MCP_TYPE=$_current_mcp_type harbor run \
            --path "$task_path" \
            --agent-import-path "$AGENT_PATH" \
            --model "$MODEL" \
            --jobs-dir "$_current_jobs_subdir" \
            -n $CONCURRENCY \
            --timeout-multiplier $TIMEOUT_MULTIPLIER \
            2>&1 | tee "${_current_jobs_subdir}/${task_id}.log" || true
    }

    mkdir -p "$PYTORCH_JOBS"

    echo "=============================================="
    echo "PyTorch Gap-Fill: 11 task runs"
    echo "=============================================="
    echo "Model: ${MODEL}"
    echo "Jobs directory: ${PYTORCH_JOBS}"
    echo ""

    # --- Baseline: sgt-007, sgt-017, sgt-024 ---
    log_section "PyTorch Gap-Fill: baseline (3 tasks)"
    _current_config="baseline"
    _current_mcp_type="none"
    _current_jobs_subdir="${PYTORCH_JOBS}/baseline"
    ensure_fresh_token_all
    mkdir -p "$_current_jobs_subdir"
    PT_BASELINE_TASKS=("sgt-007" "sgt-017" "sgt-024")
    run_tasks_parallel PT_BASELINE_TASKS _pytorch_run_single || true
    extract_all_metrics "$_current_jobs_subdir" "ccb_pytorch" "baseline"
    validate_and_report "$_current_jobs_subdir" "baseline"

    # --- SG_base: sgt-001, sgt-002, sgt-007, sgt-017, sgt-024 ---
    log_section "PyTorch Gap-Fill: sourcegraph_base (5 tasks)"
    _current_config="sourcegraph_base"
    _current_mcp_type="sourcegraph_base"
    _current_jobs_subdir="${PYTORCH_JOBS}/sourcegraph_base"
    ensure_fresh_token_all
    mkdir -p "$_current_jobs_subdir"
    PT_SGBASE_TASKS=("sgt-001" "sgt-002" "sgt-007" "sgt-017" "sgt-024")
    run_tasks_parallel PT_SGBASE_TASKS _pytorch_run_single || true
    extract_all_metrics "$_current_jobs_subdir" "ccb_pytorch" "sourcegraph_base"
    validate_and_report "$_current_jobs_subdir" "sourcegraph_base"

    # --- SG_full: sgt-007, sgt-017, sgt-024 ---
    log_section "PyTorch Gap-Fill: sourcegraph_full (3 tasks)"
    _current_config="sourcegraph_full"
    _current_mcp_type="sourcegraph_full"
    _current_jobs_subdir="${PYTORCH_JOBS}/sourcegraph_full"
    ensure_fresh_token_all
    mkdir -p "$_current_jobs_subdir"
    PT_SGFULL_TASKS=("sgt-007" "sgt-017" "sgt-024")
    run_tasks_parallel PT_SGFULL_TASKS _pytorch_run_single || true
    extract_all_metrics "$_current_jobs_subdir" "ccb_pytorch" "sourcegraph_full"
    validate_and_report "$_current_jobs_subdir" "sourcegraph_full"

    print_validation_summary "$PYTORCH_JOBS"
    echo ""
    echo "PyTorch gap-fill complete. Results: ${PYTORCH_JOBS}"
fi

# ============================================
# SWE-BENCH PRO SG_FULL GAP-FILL
# ============================================
if [ "$RUN_SWEBENCHPRO" = true ]; then
    SWE_TASKS_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks/ccb_swebenchpro/tasks"
    SWE_JOBS="runs/${CATEGORY}/swebenchpro_sgfull_gapfill_${MODEL_SHORT}_${TIMESTAMP}"

    # These 2 gap-fill tasks have no SG-indexed repos (no SOURCEGRAPH_REPO_NAME set)
    SWE_TASK_IDS=(
        "instance_ansible-ansible-eea46a0d1b99a6dadedbb6a3502d599235fa7ec3-v390e508d27db7a51eece36bb6d9698b63a5b638a"
        "instance_tutao-tutanota-f3ffe17af6e8ab007e8d461355057ad237846d9d-vbc0d9ba8f0071fbe982809910959a6ff8884dbbf"
    )

    _swe_run_single() {
        local task_id=$1 task_home=$2
        local task_path="${SWE_TASKS_DIR}/${task_id}"

        if [ ! -d "$task_path" ]; then
            echo "ERROR: Task directory not found: $task_path"
            return 1
        fi

        # No SG repos for these gap-fill tasks
        unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true

        echo "  [swebenchpro/sourcegraph_full] Task ${task_id} [HOME=$task_home]"
        BASELINE_MCP_TYPE=sourcegraph_full harbor run \
            --path "$task_path" \
            --agent-import-path "$AGENT_PATH" \
            --model "$MODEL" \
            --jobs-dir "${SWE_JOBS}/sourcegraph_full" \
            -n $CONCURRENCY \
            --timeout-multiplier $TIMEOUT_MULTIPLIER \
            2>&1 | tee "${SWE_JOBS}/sourcegraph_full/${task_id}.log" || true
    }

    mkdir -p "${SWE_JOBS}/sourcegraph_full"

    echo ""
    echo "=============================================="
    echo "SWE-bench Pro SG_full Gap-Fill: 2 task runs"
    echo "=============================================="
    echo "Model: ${MODEL}"
    echo "Jobs directory: ${SWE_JOBS}"
    echo ""

    log_section "SWE-bench Pro Gap-Fill: sourcegraph_full (2 tasks)"
    ensure_fresh_token_all
    run_tasks_parallel SWE_TASK_IDS _swe_run_single || true
    extract_all_metrics "${SWE_JOBS}/sourcegraph_full" "ccb_swebenchpro" "sourcegraph_full"
    validate_and_report "${SWE_JOBS}/sourcegraph_full" "sourcegraph_full"

    print_validation_summary "$SWE_JOBS"
    echo ""
    echo "SWE-bench Pro gap-fill complete. Results: ${SWE_JOBS}"
fi

echo ""
echo "=============================================="
echo "All Gap-Fill Runs Complete!"
echo "=============================================="
echo "Next steps:"
echo "  1. python3 scripts/generate_manifest.py"
echo "  2. /watch-benchmarks to verify coverage"
