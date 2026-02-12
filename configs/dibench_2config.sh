#!/bin/bash
# DIBench 8-Task 2-Config Comparison Script
#
# Runs selected DIBench tasks (from selected_benchmark_tasks.json) across 2 configurations:
#   1. Baseline (no MCP)
#   2. MCP-Full (Sourcegraph + Deep Search hybrid)
#
# Usage:
#   ./configs/dibench_3config.sh [OPTIONS]
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
TASKS_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks/ccb_dibench"
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
    if t['benchmark'] == 'ccb_dibench':
        print(t['task_id'])
")

# Also read task_dir for correct path resolution (task_id != directory name)
readarray -t TASK_REL_DIRS < <(python3 -c "
import json, os
tasks = json.load(open('$SELECTION_FILE'))['tasks']
for t in tasks:
    if t['benchmark'] == 'ccb_dibench':
        print(os.path.relpath(t['task_dir'], 'ccb_dibench'))
")

# Sourcegraph repo name mapping for DIBench tasks
# These override SOURCEGRAPH_REPO_NAME so the agent searches the correct repo
# DIBench uses STRIPPED repos (dependency declarations removed) to avoid leaking answers.
# The --dibench repos in sg-benchmarks contain the same modified code the agent sees locally.
declare -A TASK_SG_REPO_NAMES=(
    ["ccb_dibench-python-inducer-cgen"]="sg-benchmarks/cgen--dibench"
    ["ccb_dibench-python-rhinosec-iamactionhunter"]="sg-benchmarks/IAMActionHunter--dibench"
    ["ccb_dibench-rust-mitsuhiko-similar-asserts"]="sg-benchmarks/similar-asserts--dibench"
    ["ccb_dibench-rust-rusticata-pcap-parser"]="sg-benchmarks/pcap-parser--dibench"
    ["ccb_dibench-js-eslint-markdown"]="sg-benchmarks/markdown--dibench"
    ["ccb_dibench-js-motdotla-dotenv-expand"]="sg-benchmarks/dotenv-expand--dibench"
    ["ccb_dibench-csharp-irongut-codecoveragesummary"]="sg-benchmarks/CodeCoverageSummary--dibench"
    ["ccb_dibench-csharp-dotnetkoans"]="sg-benchmarks/DotNetKoans--dibench"
)

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
JOBS_BASE="runs/${CATEGORY}/dibench_${MODEL_SHORT}_${TIMESTAMP}"

echo "=============================================="
echo "DIBench 8-Task 2-Config Benchmark"
echo "=============================================="
echo "Model: ${MODEL}"
echo "Tasks: ${#TASK_IDS[@]}"
echo "Concurrency: ${CONCURRENCY}"
echo "Parallel jobs: ${PARALLEL_JOBS}"
echo "Jobs directory: ${JOBS_BASE}"
echo "Run baseline: ${RUN_BASELINE}"
echo "Run MCP-Full: ${RUN_FULL}"
echo ""

mkdir -p "${JOBS_BASE}"

# ============================================
# HELPER FUNCTIONS
# ============================================
log_section() {
    echo ""
    echo "========================================"
    echo "$1"
    echo "========================================"
    echo ""
}

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

# Build task_id -> rel_dir mapping for parallel access
declare -A TASK_ID_TO_REL_DIR
for (( _i=0; _i<${#TASK_IDS[@]}; _i++ )); do
    TASK_ID_TO_REL_DIR["${TASK_IDS[$_i]}"]="${TASK_REL_DIRS[$_i]}"
done

run_task_batch() {
    local mode=$1
    local mcp_type=$2
    local jobs_subdir="${JOBS_BASE}/${mode}"

    ensure_fresh_token_all

    log_section "Running DIBench - Mode: $mode"

    mkdir -p "$jobs_subdir"

    _dibench_run_single() {
        local task_id=$1
        local task_home=$2
        local rel_dir="${TASK_ID_TO_REL_DIR[$task_id]}"
        local task_path="${TASKS_DIR}/${rel_dir}"

        if [ ! -d "$task_path" ]; then
            echo "ERROR: Task directory not found: $task_path"
            return 1
        fi

        echo "Running task: $task_id ($mode) [HOME=$task_home]"

        local sg_repo="${TASK_SG_REPO_NAMES[$task_id]:-}"
        if [ -n "$sg_repo" ]; then
            export SOURCEGRAPH_REPO_NAME="$sg_repo"
        else
            unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
        fi

        BASELINE_MCP_TYPE=$mcp_type harbor run \
            --path "$task_path" \
            --agent-import-path "$AGENT_PATH" \
            --model "$MODEL" \
            --jobs-dir "$jobs_subdir" \
            -n $CONCURRENCY \
            --timeout-multiplier $TIMEOUT_MULTIPLIER \
            --force-build \
            2>&1 | tee "${jobs_subdir}/${task_id}.log" \
            || {
                echo "WARNING: Task $task_id failed (exit code: $?)"
            }
    }

    run_canary_then_batch TASK_IDS _dibench_run_single "$jobs_subdir" "$mode"

    # Extract metrics for all completed tasks in this mode
    extract_all_metrics "$jobs_subdir" "ccb_dibench" "$mode"
    validate_and_report "$jobs_subdir" "$mode"

    log_section "Completed DIBench - Mode: $mode"
}

# ============================================
# MAIN EXECUTION
# ============================================
if [ "$RUN_BASELINE" = true ]; then
    run_task_batch "baseline" "none"
fi


if [ "$RUN_FULL" = true ]; then
    run_task_batch "sourcegraph_full" "sourcegraph_full"
fi

print_validation_summary "$JOBS_BASE"

echo ""
echo "=============================================="
echo "Benchmark Complete!"
echo "=============================================="
echo "Results saved to: ${JOBS_BASE}"
echo ""
echo "View results:"
echo "  cat ${JOBS_BASE}/*/*/result.json | jq -r '.trials[].verifier_result.rewards.reward'"
