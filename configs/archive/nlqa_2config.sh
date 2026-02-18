#!/bin/bash
# NL Codebase Q&A Benchmark 2-Config Comparison Script
#
# Runs nlqa tasks (natural language codebase question-answering)
# across 2 configurations:
#   1. Baseline (no MCP)
#   2. MCP-Full (Sourcegraph + Deep Search hybrid)
#
# Usage:
#   ./configs/nlqa_2config.sh [OPTIONS]
#
# Options:
#   --baseline-only        Run only baseline (no MCP)
#   --full-only            Run only MCP-Full (sourcegraph_full)
#   --model MODEL          Override model (default: claude-opus-4-6)
#   --category CATEGORY    Run category (default: official)
#   --parallel N           Number of parallel task subshells (default: 1)
#   --task TASK_ID         Run only a specific task (e.g., nlqa-001)
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
TASKS_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks/ccb_nlqa"
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
MODEL="${MODEL:-anthropic/claude-opus-4-6}"
CONCURRENCY=2
TIMEOUT_MULTIPLIER=10
RUN_BASELINE=true
RUN_FULL=true
CATEGORY="${CATEGORY:-staging}"
TASK_FILTER=""

# All nlqa task IDs — populated by task-creation Ralphs
ALL_TASK_IDS=(
    nlqa-arch-001
    nlqa-arch-002
    nlqa-arch-003
    nlqa-flow-001
    nlqa-flow-002
    nlqa-flow-003
    nlqa-debug-001
    nlqa-debug-002
)

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
        --task)
            TASK_FILTER="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Apply task filter
if [ -n "$TASK_FILTER" ]; then
    TASK_IDS=("$TASK_FILTER")
else
    TASK_IDS=("${ALL_TASK_IDS[@]}")
fi

# Check that we have tasks to run
if [ ${#TASK_IDS[@]} -eq 0 ]; then
    echo "ERROR: No tasks defined in ALL_TASK_IDS. Populate the array with task IDs first."
    exit 1
fi

# Set up dual-account support (auto-detects second account)
setup_dual_accounts

# Sourcegraph repo name mapping for nlqa tasks
# Populated by task-creation Ralphs alongside ALL_TASK_IDS
declare -A TASK_SG_REPO_NAMES=(
    [nlqa-arch-001]="github.com/envoyproxy/envoy"
    [nlqa-arch-002]="github.com/istio/istio"
    [nlqa-arch-003]="github.com/hashicorp/terraform"
    [nlqa-flow-001]="github.com/apache/kafka"
    [nlqa-flow-002]="github.com/envoyproxy/envoy"
    [nlqa-flow-003]="github.com/argoproj/argo-cd"
    [nlqa-debug-001]="github.com/microsoft/vscode"
    [nlqa-debug-002]="github.com/cilium/cilium"
)

# Derive short model name for run directory
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
JOBS_BASE="runs/${CATEGORY}/nlqa_${MODEL_SHORT}_${TIMESTAMP}"

echo "=============================================="
echo "NL Codebase Q&A 2-Config Benchmark"
echo "=============================================="
echo "Model: ${MODEL}"
echo "Tasks: ${TASK_IDS[*]}"
echo "Task count: ${#TASK_IDS[@]}"
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
                --selected-tasks "$SCRIPT_DIR/selected_benchmark_tasks.json" \
                2>&1 || echo "  WARNING: metrics extraction failed for $(basename $result_dir)"
        fi
    done
}

_nlqa_run_single() {
    local task_id=$1
    local task_home=$2
    local config=${3:-baseline}
    local mcp_type=${4:-none}
    local jobs_base=${5:-$JOBS_BASE}
    local jobs_subdir="${jobs_base}/${config}"
    local task_path="${TASKS_DIR}/${task_id}"

    mkdir -p "$jobs_subdir"

    if [ ! -d "$task_path" ]; then
        echo "ERROR: Task directory not found: $task_path"
        return 1
    fi

    echo "Running task: $task_id ($config) [HOME=$task_home]"

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
        2>&1 | tee "${jobs_subdir}/${task_id}.log" \
        || {
            echo "WARNING: Task $task_id ($config) failed (exit code: $?)"
        }
}

run_task_batch() {
    local mode=$1
    local mcp_type=$2

    ensure_fresh_token_all
    log_section "Running NL Q&A - Mode: $mode"

    _seq_run() {
        _nlqa_run_single "$1" "$2" "$mode" "$mcp_type" "$JOBS_BASE"
    }
    run_canary_then_batch TASK_IDS _seq_run "${JOBS_BASE}/${mode}" "$mode"

    extract_all_metrics "${JOBS_BASE}/${mode}" "ccb_nlqa" "$mode"
    validate_and_report "${JOBS_BASE}/${mode}" "$mode"
    log_section "Completed NL Q&A - Mode: $mode"
}

# ============================================
# MAIN EXECUTION
# ============================================
if [ "$RUN_BASELINE" = true ] && [ "$RUN_FULL" = true ]; then
    run_paired_configs TASK_IDS _nlqa_run_single "$JOBS_BASE"

    for config in baseline sourcegraph_full; do
        if [ -d "${JOBS_BASE}/${config}" ]; then
            extract_all_metrics "${JOBS_BASE}/${config}" "ccb_nlqa" "$config"
            validate_and_report "${JOBS_BASE}/${config}" "$config"
        fi
    done
elif [ "$RUN_BASELINE" = true ]; then
    run_task_batch "baseline" "none"
elif [ "$RUN_FULL" = true ]; then
    run_task_batch "sourcegraph_full" "sourcegraph_full"
fi

print_validation_summary "$JOBS_BASE"

echo ""
echo "=============================================="
echo "NL Codebase Q&A Benchmark Complete!"
echo "=============================================="
echo "Results saved to: ${JOBS_BASE}"
echo ""
echo "View results:"
echo "  cat ${JOBS_BASE}/*/*/result.json | jq -r '.trials[].verifier_result.rewards.reward'"
