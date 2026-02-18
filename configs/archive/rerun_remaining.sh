#!/bin/bash
# Rerun script for all missing/archived tasks — uses account3 only.
#
# Tasks to rerun (24 total):
#   1. LoCoBench:      2 tasks × SG_base only = 2 runs (--path)
#   2. PyTorch:        sgt-008 + sgt-012 × BL + SG_base = 4 runs (--path)
#   3. SWE-bench Pro:  4 internetarchive × 3 configs (12) + 4 protonmail SG_full (4) = 16 runs (--dataset)
#
# Excluded:
#   - Investigation (not useful for analysis)
#   - PyTorch sgt-025 (Docker permanently broken)
#
# Usage:
#   ./configs/rerun_remaining.sh [OPTIONS]
#
# Options:
#   --parallel N        Number of parallel tasks (default: 4)
#   --locobench         Run only locobench tasks
#   --pytorch           Run only pytorch tasks
#   --swebenchpro       Run only swebenchpro tasks
#   --dry-run           Print what would run without executing

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# Agent module lives in the evals repo; add it to PYTHONPATH
AGENT_DIR="${AGENT_DIR:-$HOME/evals/custom_agents/agents/claudecode}"
export PYTHONPATH="${AGENT_DIR}:$(pwd):$PYTHONPATH"

# Shared config
source "$SCRIPT_DIR/_common.sh"

# ============================================
# LOAD CREDENTIALS
# ============================================
if [ -f ~/evals/.env.local ]; then
    echo "Loading credentials from ~/evals/.env.local..."
    source ~/evals/.env.local
else
    echo "Warning: ~/evals/.env.local not found"
fi

enforce_subscription_mode
echo "SOURCEGRAPH_ACCESS_TOKEN: ${SOURCEGRAPH_ACCESS_TOKEN:+set (${#SOURCEGRAPH_ACCESS_TOKEN} chars)}"
echo ""

# ============================================
# FORCE ACCOUNT3 ONLY
# ============================================
export SKIP_ACCOUNTS="account1 account2"

# ============================================
# CONFIGURATION
# ============================================
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
MODEL="${MODEL:-anthropic/claude-opus-4-6}"
CONCURRENCY=2
TIMEOUT_MULTIPLIER=10
CATEGORY="${CATEGORY:-staging}"
SELECTION_FILE="$SCRIPT_DIR/selected_benchmark_tasks.json"

# Disable fail-fast so one suite's failure doesn't block others
FAIL_FAST=false

RUN_LOCOBENCH=true
RUN_PYTORCH=true
RUN_SWEBENCHPRO=true
DRY_RUN=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --parallel)
            PARALLEL_JOBS="$2"
            shift 2
            ;;
        --locobench)
            RUN_PYTORCH=false; RUN_SWEBENCHPRO=false
            shift
            ;;
        --pytorch)
            RUN_LOCOBENCH=false; RUN_SWEBENCHPRO=false
            shift
            ;;
        --swebenchpro)
            RUN_LOCOBENCH=false; RUN_PYTORCH=false
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            echo "Unknown option: $1"; exit 1
            ;;
    esac
done

# Account setup (will only pick account3 due to SKIP_ACCOUNTS)
setup_dual_accounts
ensure_fresh_token_all

# ============================================
# SHARED HELPERS
# ============================================
_model_lower=$(echo "$MODEL" | awk -F/ '{print $NF}' | tr '[:upper:]' '[:lower:]')
case "$_model_lower" in
    *opus*)   MODEL_SHORT="opus" ;;
    *sonnet*) MODEL_SHORT="sonnet" ;;
    *haiku*)  MODEL_SHORT="haiku" ;;
    *)        MODEL_SHORT=$(echo "$_model_lower" | tr -d '-' | tr -d '_' | cut -c1-8) ;;
esac

TIMESTAMP=$(date +%Y%m%d_%H%M%S)

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

log_section() {
    echo ""
    echo "========================================"
    echo "$1"
    echo "========================================"
    echo ""
}

# ============================================
# 1. INVESTIGATION — SKIPPED (not useful)
# ============================================

# ============================================
# 2. LOCOBENCH SG_BASE — 2 tasks
# ============================================
if [ "$RUN_LOCOBENCH" = true ]; then
    LOCOBENCH_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks/ccb_locobench/tasks"
    LOCO_JOBS="runs/${CATEGORY}/locobench_gapfill_${MODEL_SHORT}_${TIMESTAMP}"

    LOCO_TASK_IDS=(
        "c_api_graphql_expert_079_architectural_understanding_expert_01"
        "c_api_graphql_expert_079_cross_file_refactoring_expert_01"
    )

    # Resolve SG repo from docker-compose.yaml (same as locobench_3config.sh)
    get_sg_repo_name() {
        local task_dir=$1
        local dc_file="${task_dir}/environment/docker-compose.yaml"
        if [ -f "$dc_file" ]; then
            local proj_id=$(grep 'LOCOBENCH_PROJECT_ID=' "$dc_file" | head -1 | sed 's/.*LOCOBENCH_PROJECT_ID=//')
            if [ -n "$proj_id" ]; then
                echo "sg-benchmarks/locobench-${proj_id}"
                return
            fi
        fi
        echo ""
    }

    _loco_run() {
        local task_id=$1
        local task_home=$2
        local task_path="${LOCOBENCH_DIR}/${task_id}"
        local sg_repo=$(get_sg_repo_name "$task_path")
        [ -n "$sg_repo" ] && export SOURCEGRAPH_REPO_NAME="$sg_repo" || unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
        echo "  Running $task_id (sourcegraph_base) SG_REPO=$sg_repo [HOME=$task_home]"
        BASELINE_MCP_TYPE=sourcegraph_base harbor run \
            --path "$task_path" \
            --agent-import-path "$AGENT_PATH" \
            --model "$MODEL" \
            --jobs-dir "$LOCO_JOBS/sourcegraph_base" \
            -n $CONCURRENCY \
            --timeout-multiplier $TIMEOUT_MULTIPLIER \
            2>&1 | tee "$LOCO_JOBS/sourcegraph_base/${task_id}.log" || true
    }

    if [ "$DRY_RUN" = true ]; then
        log_section "[DRY RUN] LoCoBench SG_base: 2 tasks -> $LOCO_JOBS"
    else
        log_section "LoCoBench SG_base — 2 gap-fill tasks"
        mkdir -p "$LOCO_JOBS/sourcegraph_base"
        ensure_fresh_token_all
        run_tasks_parallel LOCO_TASK_IDS _loco_run || true
        extract_all_metrics "$LOCO_JOBS/sourcegraph_base" "ccb_locobench" "sourcegraph_base"
        validate_and_report "$LOCO_JOBS/sourcegraph_base" "sourcegraph_base"
    fi
fi

# ============================================
# 3. PYTORCH — sgt-008, sgt-012 (BL + SG_base only)
#    SG_full already has these. sgt-025 dropped (Docker permanently broken).
# ============================================
if [ "$RUN_PYTORCH" = true ]; then
    PYTORCH_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks/ccb_pytorch"
    PT_JOBS="runs/${CATEGORY}/pytorch_rerun_${MODEL_SHORT}_${TIMESTAMP}"

    PT_TASKS=("sgt-008" "sgt-012")

    declare -A PT_SG_REPOS=(
        ["sgt-008"]="github.com/pytorch/pytorch"
        ["sgt-012"]="github.com/pytorch/pytorch"
    )

    _pt_run() {
        local task_id=$1
        local task_home=$2
        local task_path="${PYTORCH_DIR}/${task_id}"
        local sg_repo="${PT_SG_REPOS[$task_id]:-}"
        [ -n "$sg_repo" ] && export SOURCEGRAPH_REPO_NAME="$sg_repo" || unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
        echo "  Running $task_id ($PT_MODE) [HOME=$task_home]"
        BASELINE_MCP_TYPE=$PT_MCP_TYPE harbor run \
            --path "$task_path" \
            --agent-import-path "$AGENT_PATH" \
            --model "$MODEL" \
            --jobs-dir "$PT_JOBS/$PT_MODE" \
            -n $CONCURRENCY \
            --timeout-multiplier $TIMEOUT_MULTIPLIER \
            2>&1 | tee "$PT_JOBS/$PT_MODE/${task_id}.log" || true
    }

    if [ "$DRY_RUN" = true ]; then
        log_section "[DRY RUN] PyTorch: BL+SG_base(2 each) -> $PT_JOBS"
    else
        mkdir -p "$PT_JOBS"

        # Baseline: sgt-008, sgt-012
        PT_MODE="baseline"; PT_MCP_TYPE="none"
        log_section "PyTorch — baseline (sgt-008, sgt-012)"
        mkdir -p "$PT_JOBS/baseline"
        ensure_fresh_token_all
        run_tasks_parallel PT_TASKS _pt_run || true
        extract_all_metrics "$PT_JOBS/baseline" "ccb_pytorch" "baseline"
        validate_and_report "$PT_JOBS/baseline" "baseline"

        # SG_base: sgt-008, sgt-012
        PT_MODE="sourcegraph_base"; PT_MCP_TYPE="sourcegraph_base"
        log_section "PyTorch — sourcegraph_base (sgt-008, sgt-012)"
        mkdir -p "$PT_JOBS/sourcegraph_base"
        ensure_fresh_token_all
        run_tasks_parallel PT_TASKS _pt_run || true
        extract_all_metrics "$PT_JOBS/sourcegraph_base" "ccb_pytorch" "sourcegraph_base"
        validate_and_report "$PT_JOBS/sourcegraph_base" "sourcegraph_base"

        print_validation_summary "$PT_JOBS"
    fi
fi

# ============================================
# 4. SWE-BENCH PRO
#    Baseline + SG_base: 4 internetarchive tasks each
#    SG_full: 4 internetarchive + 4 protonmail
#    Uses --dataset swebenchpro mode (sequential to avoid timestamp collision)
# ============================================
if [ "$RUN_SWEBENCHPRO" = true ]; then
    SWE_JOBS="runs/${CATEGORY}/swebenchpro_rerun_${MODEL_SHORT}_${TIMESTAMP}"

    # 4 internetarchive tasks (missing from all 3 configs)
    SWE_INTERNET_TASKS=(
        "instance_internetarchive__openlibrary-7f6b722a10f822171501d027cad60afe53337732-ve8c8d62a2b60610a3c4631f5f23ed866bada9818"
        "instance_internetarchive__openlibrary-92db3454aeaa02f89b4cdbc3103f7e95c9759f92-v2c55207218fb8a0138425cbf7d9675272e240b90"
        "instance_internetarchive__openlibrary-c506c1b0b678892af5cb22c1c1dbc35d96787a0a-v0f5aece3601a5b4419f7ccec1dbda2071be28ee4"
        "instance_internetarchive__openlibrary-d109cc7e6e161170391f98f9a6fa1d02534c18e4-ve8c8d62a2b60610a3c4631f5f23ed866bada9818"
    )

    # 4 protonmail tasks (missing from SG_full only)
    SWE_PROTON_TASKS=(
        "instance_protonmail__webclients-369fd37de29c14c690cb3b1c09a949189734026f"
        "instance_protonmail__webclients-8be4f6cb9380fcd2e67bcb18cef931ae0d4b869c"
        "instance_protonmail__webclients-c6f65d205c401350a226bb005f42fac1754b0b5b"
        "instance_protonmail__webclients-caf10ba9ab2677761c88522d1ba8ad025779c492"
    )

    # SG repo mapping (from swebenchpro_3config.sh)
    declare -A SWE_SG_REPOS=(
        ["instance_internetarchive__openlibrary-7f6b722a10f822171501d027cad60afe53337732-ve8c8d62a2b60610a3c4631f5f23ed866bada9818"]="sg-benchmarks/openlibrary--7f6b722a"
        ["instance_internetarchive__openlibrary-92db3454aeaa02f89b4cdbc3103f7e95c9759f92-v2c55207218fb8a0138425cbf7d9675272e240b90"]="sg-benchmarks/openlibrary--92db3454"
        ["instance_internetarchive__openlibrary-c506c1b0b678892af5cb22c1c1dbc35d96787a0a-v0f5aece3601a5b4419f7ccec1dbda2071be28ee4"]="sg-benchmarks/openlibrary--c506c1b0"
        ["instance_internetarchive__openlibrary-d109cc7e6e161170391f98f9a6fa1d02534c18e4-ve8c8d62a2b60610a3c4631f5f23ed866bada9818"]="sg-benchmarks/openlibrary--d109cc7e"
        ["instance_protonmail__webclients-369fd37de29c14c690cb3b1c09a949189734026f"]="sg-benchmarks/webclients--369fd37d"
        ["instance_protonmail__webclients-8be4f6cb9380fcd2e67bcb18cef931ae0d4b869c"]="sg-benchmarks/webclients--8be4f6cb"
        ["instance_protonmail__webclients-c6f65d205c401350a226bb005f42fac1754b0b5b"]="sg-benchmarks/webclients--c6f65d20"
        ["instance_protonmail__webclients-caf10ba9ab2677761c88522d1ba8ad025779c492"]="sg-benchmarks/webclients--caf10ba9"
    )

    # SWE-bench Pro uses --dataset mode which must run SEQUENTIALLY (timestamp collision)
    _swe_run_sequential() {
        local mode=$1
        local mcp_type=$2
        local jobs_subdir="$SWE_JOBS/$mode"
        shift 2
        local task_ids=("$@")

        mkdir -p "$jobs_subdir"
        ensure_fresh_token_all

        for task_id in "${task_ids[@]}"; do
            local sg_repo="${SWE_SG_REPOS[$task_id]:-}"
            if [ -n "$sg_repo" ]; then
                export SOURCEGRAPH_REPO_NAME="$sg_repo"
                echo "  [${mode}] Task ${task_id} -> SG_REPO=${sg_repo}"
            else
                unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
            fi

            echo "  Running: $task_id ($mode)"
            HOME="${CLAUDE_HOMES[0]}" \
            BASELINE_MCP_TYPE=$mcp_type harbor run \
                --dataset swebenchpro \
                -t "$task_id" \
                --agent-import-path "$AGENT_PATH" \
                --model "$MODEL" \
                --jobs-dir "$jobs_subdir" \
                -n $CONCURRENCY \
                --timeout-multiplier $TIMEOUT_MULTIPLIER \
                2>&1 | tee "${jobs_subdir}/${task_id}.log" || true

            # Sleep to avoid timestamp collisions
            sleep 3
        done

        extract_all_metrics "$jobs_subdir" "ccb_swebenchpro" "$mode"
        validate_and_report "$jobs_subdir" "$mode"
    }

    if [ "$DRY_RUN" = true ]; then
        log_section "[DRY RUN] SWE-bench Pro: BL(4) + SG_base(4) + SG_full(8) -> $SWE_JOBS"
    else
        mkdir -p "$SWE_JOBS"

        # Baseline: 4 internetarchive (sequential for --dataset mode)
        log_section "SWE-bench Pro — baseline (4 internetarchive)"
        _swe_run_sequential "baseline" "none" "${SWE_INTERNET_TASKS[@]}"

        # SG_base: 4 internetarchive
        log_section "SWE-bench Pro — sourcegraph_base (4 internetarchive)"
        _swe_run_sequential "sourcegraph_base" "sourcegraph_base" "${SWE_INTERNET_TASKS[@]}"

        # SG_full: 4 internetarchive + 4 protonmail = 8
        SWE_FULL_TASKS=("${SWE_INTERNET_TASKS[@]}" "${SWE_PROTON_TASKS[@]}")
        log_section "SWE-bench Pro — sourcegraph_full (4 internetarchive + 4 protonmail)"
        _swe_run_sequential "sourcegraph_full" "sourcegraph_full" "${SWE_FULL_TASKS[@]}"

        print_validation_summary "$SWE_JOBS"
    fi
fi

# ============================================
# SUMMARY
# ============================================
echo ""
echo "=============================================="
echo "Rerun Complete!"
echo "=============================================="
echo "Account: account3 only"
echo ""
[ "$RUN_LOCOBENCH" = true ]     && echo "  LoCoBench:     ${LOCO_JOBS:-N/A}"
[ "$RUN_PYTORCH" = true ]       && echo "  PyTorch:       ${PT_JOBS:-N/A}"
[ "$RUN_SWEBENCHPRO" = true ]   && echo "  SWE-bench Pro: ${SWE_JOBS:-N/A}"
echo ""
echo "Regenerate MANIFEST with:"
echo "  python3 scripts/generate_manifest.py"
