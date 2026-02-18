#!/bin/bash
# Gap-Fill: Run remaining missing tasks across PyTorch and SWE-bench Pro.
#
# PyTorch:      11 task runs (3 new tasks x3 configs + 2 SG_base reruns)
# SWE-bench Pro: 2 task runs (2 gap-fill tasks on SG_full only)
# Total:        13 task runs
#
# Usage:
#   ./configs/gapfill_remaining.sh [OPTIONS]
#
# Options:
#   --pytorch-only       Run only PyTorch gap tasks
#   --swebenchpro-only   Run only SWE-bench Pro gap tasks
#   --parallel N         Override parallel job count
#   --dry-run            Show what would be run without executing

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
RUN_PYTORCH=true
RUN_SWEBENCHPRO=true
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --pytorch-only) RUN_SWEBENCHPRO=false; shift ;;
        --swebenchpro-only) RUN_PYTORCH=false; shift ;;
        --parallel) PARALLEL_JOBS="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

setup_multi_accounts

if [ -z "$SOURCEGRAPH_ACCESS_TOKEN" ]; then
    echo "WARNING: SOURCEGRAPH_ACCESS_TOKEN not set — SG modes will lack repo context"
fi

SELECTION_FILE="$SCRIPT_DIR/selected_benchmark_tasks.json"

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
# Missing tasks: sgt-007, sgt-017, sgt-024 (never ran, all 3 configs)
# Rerun tasks:   sgt-001, sgt-002 (errored on SG_base only)

PYTORCH_TASKS_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks/ccb_pytorch"

# SG repo mappings (matching pytorch_3config.sh)
declare -A PT_SG_REPOS=(
    ["sgt-001"]="sg-benchmarks/pytorch--ca246612"
    ["sgt-002"]="sg-benchmarks/pytorch--ca246612"
    ["sgt-007"]="sg-benchmarks/pytorch--a61b434d"
    ["sgt-017"]="sg-benchmarks/pytorch--cbe1a35d"
    ["sgt-024"]="sg-benchmarks/pytorch--cbe1a35d"
)

run_pytorch_gap() {
    local JOBS_BASE="runs/${CATEGORY}/pytorch_gapfill_${MODEL_SHORT}_${TIMESTAMP}"
    mkdir -p "${JOBS_BASE}"

    echo "=============================================="
    echo "PyTorch Gap-Fill (11 task runs)"
    echo "=============================================="
    echo "Jobs directory: ${JOBS_BASE}"

    _pt_run_single() {
        local task_id=$1 task_home=$2
        local task_path="${PYTORCH_TASKS_DIR}/${task_id}"

        if [ ! -d "$task_path" ]; then
            echo "ERROR: Task directory not found: $task_path"
            return 1
        fi

        local sg_repo="${PT_SG_REPOS[$task_id]:-}"
        if [ -n "$sg_repo" ]; then
            export SOURCEGRAPH_REPO_NAME="$sg_repo"
        else
            unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
        fi
        echo "  [${_PT_MODE}] Task ${task_id} [HOME=$task_home]"
        BASELINE_MCP_TYPE=$_PT_MCP_TYPE harbor run \
            --path "$task_path" \
            --agent-import-path "$AGENT_PATH" \
            --model "$MODEL" \
            --jobs-dir "$_PT_JOBS_SUBDIR" \
            -n $CONCURRENCY \
            --timeout-multiplier $TIMEOUT_MULTIPLIER \
            2>&1 | tee "${_PT_JOBS_SUBDIR}/${task_id}.log" || true
    }

    # --- Baseline: 3 new tasks ---
    log_section "PyTorch Gap-Fill: baseline (3 tasks)"
    _PT_MODE="baseline"
    _PT_MCP_TYPE="none"
    _PT_JOBS_SUBDIR="${JOBS_BASE}/baseline"
    ensure_fresh_token_all
    mkdir -p "$_PT_JOBS_SUBDIR"
    PT_BASELINE_TASKS=("sgt-007" "sgt-017" "sgt-024")
    if [ "$DRY_RUN" = true ]; then
        echo "  [DRY-RUN] Would run: ${PT_BASELINE_TASKS[*]}"
    else
        run_tasks_parallel PT_BASELINE_TASKS _pt_run_single || true
        extract_all_metrics "$_PT_JOBS_SUBDIR" "ccb_pytorch" "baseline"
        validate_and_report "$_PT_JOBS_SUBDIR" "baseline"
    fi

    # --- SG_base: 5 tasks (3 new + 2 reruns) ---
    log_section "PyTorch Gap-Fill: sourcegraph_base (5 tasks)"
    _PT_MODE="sourcegraph_base"
    _PT_MCP_TYPE="sourcegraph_base"
    _PT_JOBS_SUBDIR="${JOBS_BASE}/sourcegraph_base"
    ensure_fresh_token_all
    mkdir -p "$_PT_JOBS_SUBDIR"
    PT_SGBASE_TASKS=("sgt-001" "sgt-002" "sgt-007" "sgt-017" "sgt-024")
    if [ "$DRY_RUN" = true ]; then
        echo "  [DRY-RUN] Would run: ${PT_SGBASE_TASKS[*]}"
    else
        run_tasks_parallel PT_SGBASE_TASKS _pt_run_single || true
        extract_all_metrics "$_PT_JOBS_SUBDIR" "ccb_pytorch" "sourcegraph_base"
        validate_and_report "$_PT_JOBS_SUBDIR" "sourcegraph_base"
    fi

    # --- SG_full: 3 new tasks ---
    log_section "PyTorch Gap-Fill: sourcegraph_full (3 tasks)"
    _PT_MODE="sourcegraph_full"
    _PT_MCP_TYPE="sourcegraph_full"
    _PT_JOBS_SUBDIR="${JOBS_BASE}/sourcegraph_full"
    ensure_fresh_token_all
    mkdir -p "$_PT_JOBS_SUBDIR"
    PT_SGFULL_TASKS=("sgt-007" "sgt-017" "sgt-024")
    if [ "$DRY_RUN" = true ]; then
        echo "  [DRY-RUN] Would run: ${PT_SGFULL_TASKS[*]}"
    else
        run_tasks_parallel PT_SGFULL_TASKS _pt_run_single || true
        extract_all_metrics "$_PT_JOBS_SUBDIR" "ccb_pytorch" "sourcegraph_full"
        validate_and_report "$_PT_JOBS_SUBDIR" "sourcegraph_full"
    fi

    print_validation_summary "$JOBS_BASE"
    echo "PyTorch gap-fill results: ${JOBS_BASE}"
}

# ============================================
# SWE-BENCH PRO GAP-FILL (SG_full only)
# ============================================
# 2 gap-fill tasks that ran on baseline + SG_base but not SG_full.
# These have no SG-indexed repos (expected — MCP runs without repo context).

SWE_TASKS_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks/ccb_swebenchpro/tasks"

SWE_SGFULL_TASKS=(
    "instance_ansible-ansible-eea46a0d1b99a6dadedbb6a3502d599235fa7ec3-v390e508d27db7a51eece36bb6d9698b63a5b638a"
    "instance_tutao-tutanota-f3ffe17af6e8ab007e8d461355057ad237846d9d-vbc0d9ba8f0071fbe982809910959a6ff8884dbbf"
)

run_swebenchpro_gap() {
    local JOBS_BASE="runs/${CATEGORY}/swebenchpro_gapfill_sgfull_${MODEL_SHORT}_${TIMESTAMP}"
    mkdir -p "${JOBS_BASE}"

    echo "=============================================="
    echo "SWE-bench Pro Gap-Fill: SG_full only (2 tasks)"
    echo "=============================================="
    echo "Jobs directory: ${JOBS_BASE}"

    local jobs_subdir="${JOBS_BASE}/sourcegraph_full"
    ensure_fresh_token_all
    mkdir -p "$jobs_subdir"

    _swe_run_single() {
        local task_id=$1 task_home=$2
        local task_path="${SWE_TASKS_DIR}/${task_id}"

        if [ ! -d "$task_path" ]; then
            echo "ERROR: Task directory not found: $task_path"
            return 1
        fi

        # No SG repos for these gap-fill tasks
        unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
        echo "  [sourcegraph_full] Task ${task_id} [HOME=$task_home]"
        BASELINE_MCP_TYPE=sourcegraph_full harbor run \
            --path "$task_path" \
            --agent-import-path "$AGENT_PATH" \
            --model "$MODEL" \
            --jobs-dir "$jobs_subdir" \
            -n $CONCURRENCY \
            --timeout-multiplier $TIMEOUT_MULTIPLIER \
            2>&1 | tee "${jobs_subdir}/${task_id}.log" || true
    }

    if [ "$DRY_RUN" = true ]; then
        echo "  [DRY-RUN] Would run SG_full: ${SWE_SGFULL_TASKS[*]}"
    else
        run_tasks_parallel SWE_SGFULL_TASKS _swe_run_single || true
        extract_all_metrics "$jobs_subdir" "ccb_swebenchpro" "sourcegraph_full"
        validate_and_report "$jobs_subdir" "sourcegraph_full"
    fi

    print_validation_summary "$JOBS_BASE"
    echo "SWE-bench Pro gap-fill results: ${JOBS_BASE}"
}

# ============================================
# MAIN EXECUTION
# ============================================
echo "=============================================="
echo "Combined Gap-Fill: 13 remaining task runs"
echo "=============================================="
echo "Model: ${MODEL}"
echo "Parallel jobs: ${PARALLEL_JOBS}"
echo "PyTorch: ${RUN_PYTORCH}"
echo "SWE-bench Pro: ${RUN_SWEBENCHPRO}"
echo "Dry run: ${DRY_RUN}"
echo ""

if [ "$RUN_PYTORCH" = true ]; then
    run_pytorch_gap
fi

if [ "$RUN_SWEBENCHPRO" = true ]; then
    run_swebenchpro_gap
fi

echo ""
echo "=============================================="
echo "Gap-Fill Complete!"
echo "=============================================="
echo "Next: python3 scripts/generate_manifest.py"
