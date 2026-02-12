#!/bin/bash
# LoCoBench-Agent 2-Config Comparison Script
#
# Runs selected LoCoBench tasks (from selected_benchmark_tasks.json) across 2 configurations:
#   1. Baseline (no MCP)
#   2. MCP-Full (Sourcegraph + Deep Search hybrid)
#
# Usage:
#   ./configs/locobench_3config.sh [OPTIONS]
#
# Options:
#   --baseline-only        Run only baseline (no MCP)
#   --full-only            Run only MCP-Full (sourcegraph_full)
#   --model MODEL          Override model (default: claude-opus-4-6)
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
TASKS_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks/ccb_locobench/tasks"
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
    if t['benchmark'] == 'ccb_locobench':
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
JOBS_BASE="runs/${CATEGORY}/locobench_selected_${MODEL_SHORT}_${TIMESTAMP}"

echo "=============================================="
echo "LoCoBench-Agent Selected-Task 2-Config Benchmark"
echo "=============================================="
echo "Model: ${MODEL}"
echo "Tasks: ${#TASK_IDS[@]}"
echo "Concurrency: ${CONCURRENCY}"
echo "Parallel jobs: ${PARALLEL_JOBS}"
echo "Jobs directory: ${JOBS_BASE}"
echo "Run baseline: ${RUN_BASELINE}"
echo "Run MCP-Full: ${RUN_FULL}"
echo ""

# Create task list file for Harbor
TASK_LIST_FILE="${JOBS_BASE}/task_list.txt"
mkdir -p "${JOBS_BASE}"

for task_id in "${TASK_IDS[@]}"; do
    echo "${TASKS_DIR}/${task_id}" >> "${TASK_LIST_FILE}"
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

# Resolve SOURCEGRAPH_REPO_NAME from a locobench task's docker-compose.yaml
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

# Run MCP mode tasks with parallel support; SOURCEGRAPH_REPO_NAME set per task
run_mcp_task_batch() {
    local mode=$1
    local mcp_type=$2
    local jobs_subdir="${JOBS_BASE}/${mode}"
    ensure_fresh_token_all
    mkdir -p "$jobs_subdir"

    _locobench_mcp_run_single() {
        local task_id=$1
        local task_home=$2
        local task_path="${TASKS_DIR}/${task_id}"
        local sg_repo=$(get_sg_repo_name "$task_path")
        if [ -n "$sg_repo" ]; then
            export SOURCEGRAPH_REPO_NAME="$sg_repo"
            echo "  [${mode}] Task ${task_id} -> SOURCEGRAPH_REPO_NAME=${sg_repo} [HOME=$task_home]"
        else
            unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
            echo "  [${mode}] Task ${task_id} -> no SG repo mapping [HOME=$task_home]"
        fi
        BASELINE_MCP_TYPE=$mcp_type harbor run \
            --path "$task_path" \
            --agent-import-path "$AGENT_PATH" \
            --model "$MODEL" \
            --jobs-dir "$jobs_subdir" \
            -n $CONCURRENCY \
            --timeout-multiplier $TIMEOUT_MULTIPLIER \
            --force-build \
            2>&1 | tee "${jobs_subdir}/${task_id}.log" || true
    }

    run_canary_then_batch TASK_IDS _locobench_mcp_run_single "$jobs_subdir" "$mode"

    extract_all_metrics "$jobs_subdir" "ccb_locobench" "$mode"
    validate_and_report "$jobs_subdir" "$mode"
}

# ============================================
# RUN BASELINE (no MCP)
# ============================================
if [ "$RUN_BASELINE" = true ]; then
    echo ""
    echo "[BASELINE] Starting selected-task baseline run..."
    echo ""

    BASELINE_JOBS="${JOBS_BASE}/baseline"
    ensure_fresh_token_all
    mkdir -p "$BASELINE_JOBS"

    _locobench_baseline_run_single() {
        local task_id=$1
        local task_home=$2
        local task_path="${TASKS_DIR}/${task_id}"
        echo "  [baseline] Task ${task_id} [HOME=$task_home]"
        BASELINE_MCP_TYPE=none harbor run \
            --path "$task_path" \
            --agent-import-path "${AGENT_PATH}" \
            --model "${MODEL}" \
            --jobs-dir "${BASELINE_JOBS}" \
            -n ${CONCURRENCY} \
            --timeout-multiplier ${TIMEOUT_MULTIPLIER} \
            --force-build \
            2>&1 | tee "${BASELINE_JOBS}/${task_id}.log" || true
    }

    run_canary_then_batch TASK_IDS _locobench_baseline_run_single "$BASELINE_JOBS" "baseline"

    extract_all_metrics "${BASELINE_JOBS}" "ccb_locobench" "baseline"
    validate_and_report "${BASELINE_JOBS}" "baseline"
fi

# ============================================
# RUN MCP-Full (sourcegraph_full)
# Per-task iteration to set SOURCEGRAPH_REPO_NAME from docker-compose.yaml
# ============================================
if [ "$RUN_FULL" = true ]; then
    echo ""
    echo "[MCP-Full] Starting per-task MCP-Full run..."
    echo ""

    run_mcp_task_batch "sourcegraph_full" "sourcegraph_full"
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
    echo "  # Baseline summary"
    echo "  cat ${JOBS_BASE}/baseline/*/result.json | jq -s 'map(.trials[].verifier_result.rewards.reward) | {mean: (add/length), count: length}'"
    echo ""
fi
if [ "$RUN_FULL" = true ]; then
    echo "  # MCP-Full summary"
    echo "  cat ${JOBS_BASE}/sourcegraph_full/*/result.json | jq -s 'map(.trials[].verifier_result.rewards.reward) | {mean: (add/length), count: length}'"
fi
