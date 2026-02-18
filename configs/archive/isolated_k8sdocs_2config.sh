#!/bin/bash
# K8s Docs Isolated vs Full MCP Comparison
#
# Runs all 5 Kubernetes documentation tasks across 2 configurations:
#   1. sourcegraph_isolated (sparse checkout: only target package locally)
#   2. sourcegraph_full (full repo + full MCP, for comparison)
#
# Usage:
#   ./configs/isolated_k8sdocs_2config.sh [OPTIONS]
#
# Options:
#   --isolated-only        Run only isolated config
#   --full-only            Run only full config (comparison baseline)
#   --model MODEL          Override model (default: claude-opus-4-6)
#   --category CATEGORY    Run category (default: official)
#   --parallel N           Number of parallel task subshells (default: 1)
#
# Prerequisites:
#   - ~/evals/.env.local with USE_SUBSCRIPTION=true
#   - SOURCEGRAPH_ACCESS_TOKEN in .env.local
#   - Dockerfile.isolated present in each task's environment/ dir

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
    echo "ERROR: SOURCEGRAPH_ACCESS_TOKEN required for isolated config"
    exit 1
fi
echo ""

ensure_fresh_token_all

# ============================================
# CONFIGURATION
# ============================================
TASKS_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks/ccb_k8sdocs"
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
MODEL="${MODEL:-anthropic/claude-opus-4-6}"
CONCURRENCY=2
TIMEOUT_MULTIPLIER=3
RUN_ISOLATED=true
RUN_FULL=true
CATEGORY="${CATEGORY:-staging}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --isolated-only)
            RUN_FULL=false
            shift
            ;;
        --full-only)
            RUN_ISOLATED=false
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

# Set up dual-account support
setup_dual_accounts

# Load task IDs
SELECTION_FILE="$SCRIPT_DIR/selected_benchmark_tasks.json"
if [ ! -f "$SELECTION_FILE" ]; then
    echo "ERROR: selected_benchmark_tasks.json not found at $SELECTION_FILE"
    exit 1
fi

readarray -t TASK_IDS < <(python3 -c "
import json
tasks = json.load(open('$SELECTION_FILE'))['tasks']
for t in tasks:
    if t['benchmark'] == 'ccb_k8sdocs':
        print(t['task_id'])
")

# Derive model short name
_model_lower=$(echo "$MODEL" | awk -F/ '{print $NF}' | tr '[:upper:]' '[:lower:]')
case "$_model_lower" in
    *opus*)   MODEL_SHORT="opus" ;;
    *sonnet*) MODEL_SHORT="sonnet" ;;
    *haiku*)  MODEL_SHORT="haiku" ;;
    *)        MODEL_SHORT=$(echo "$_model_lower" | tr -d '-' | tr -d '_' | cut -c1-8) ;;
esac

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
JOBS_BASE="runs/${CATEGORY}/k8s_docs_isolated_${MODEL_SHORT}_${TIMESTAMP}"

echo "=============================================="
echo "K8s Docs Isolated vs Full MCP Comparison"
echo "=============================================="
echo "Model: ${MODEL}"
echo "Tasks: ${#TASK_IDS[@]}"
echo "Concurrency: ${CONCURRENCY}"
echo "Parallel jobs: ${PARALLEL_JOBS}"
echo "Jobs directory: ${JOBS_BASE}"
echo "Run isolated: ${RUN_ISOLATED}"
echo "Run full: ${RUN_FULL}"
echo ""

mkdir -p "${JOBS_BASE}"

# ============================================
# HELPER: Dockerfile swap for isolated mode
# ============================================
swap_to_isolated() {
    local task_dir=$1
    local dockerfile="${task_dir}/environment/Dockerfile"
    local isolated="${task_dir}/environment/Dockerfile.isolated"
    local backup="${task_dir}/environment/Dockerfile.original"

    if [ ! -f "$isolated" ]; then
        echo "WARNING: No Dockerfile.isolated for $(basename $task_dir), skipping"
        return 1
    fi

    # Backup original and swap
    cp "$dockerfile" "$backup"
    cp "$isolated" "$dockerfile"
    return 0
}

restore_dockerfile() {
    local task_dir=$1
    local dockerfile="${task_dir}/environment/Dockerfile"
    local backup="${task_dir}/environment/Dockerfile.original"

    if [ -f "$backup" ]; then
        mv "$backup" "$dockerfile"
    fi
}

# Extract per-task metrics
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

# ============================================
# RUN ISOLATED (sparse checkout + MCP)
# ============================================
if [ "$RUN_ISOLATED" = true ]; then
    ensure_fresh_token_all
    echo ""
    echo "[ISOLATED] Starting 5-task isolated MCP run..."
    echo "[ISOLATED] Swapping Dockerfiles to sparse-checkout versions..."
    echo ""

    # Swap all Dockerfiles to isolated versions
    SWAP_FAILED=false
    for task_id in "${TASK_IDS[@]}"; do
        task_dir="${TASKS_DIR}/${task_id}"
        if ! swap_to_isolated "$task_dir"; then
            SWAP_FAILED=true
        fi
    done

    if [ "$SWAP_FAILED" = true ]; then
        echo "WARNING: Some tasks missing Dockerfile.isolated, running available tasks"
    fi

    # Run with isolated mode
    SOURCEGRAPH_REPO_NAME="kubernetes/kubernetes" \
    BASELINE_MCP_TYPE=sourcegraph_isolated harbor run \
        --path "${TASKS_DIR}" \
        --task-name "*" \
        --agent-import-path "${AGENT_PATH}" \
        --model "${MODEL}" \
        --jobs-dir "${JOBS_BASE}/sourcegraph_isolated" \
        -n ${CONCURRENCY} \
        --timeout-multiplier ${TIMEOUT_MULTIPLIER} \
        2>&1 | tee "${JOBS_BASE}/sourcegraph_isolated.log"

    # Restore all Dockerfiles
    echo "[ISOLATED] Restoring original Dockerfiles..."
    for task_id in "${TASK_IDS[@]}"; do
        restore_dockerfile "${TASKS_DIR}/${task_id}"
    done

    extract_all_metrics "${JOBS_BASE}/sourcegraph_isolated" "ccb_k8sdocs" "sourcegraph_isolated"
    validate_and_report "${JOBS_BASE}/sourcegraph_isolated" "sourcegraph_isolated"
fi

# ============================================
# RUN FULL (full repo + full MCP, comparison)
# ============================================
if [ "$RUN_FULL" = true ]; then
    ensure_fresh_token_all
    echo ""
    echo "[FULL] Starting 5-task MCP-Full comparison run..."
    echo ""

    SOURCEGRAPH_REPO_NAME="sg-benchmarks/kubernetes--stripped" \
    BASELINE_MCP_TYPE=sourcegraph_full harbor run \
        --path "${TASKS_DIR}" \
        --task-name "*" \
        --agent-import-path "${AGENT_PATH}" \
        --model "${MODEL}" \
        --jobs-dir "${JOBS_BASE}/sourcegraph_full" \
        -n ${CONCURRENCY} \
        --timeout-multiplier ${TIMEOUT_MULTIPLIER} \
        2>&1 | tee "${JOBS_BASE}/sourcegraph_full.log"

    extract_all_metrics "${JOBS_BASE}/sourcegraph_full" "ccb_k8sdocs" "sourcegraph_full"
    validate_and_report "${JOBS_BASE}/sourcegraph_full" "sourcegraph_full"
fi

print_validation_summary "$JOBS_BASE"

echo ""
echo "=============================================="
echo "Isolated vs Full Comparison Complete!"
echo "=============================================="
echo "Results saved to: ${JOBS_BASE}"
echo ""
echo "Compare results:"
if [ "$RUN_ISOLATED" = true ]; then
    echo "  # Isolated summary"
    echo "  cat ${JOBS_BASE}/sourcegraph_isolated/*/result.json | jq -s 'map(.trials[].verifier_result.rewards.reward) | {mean: (add/length), count: length}'"
    echo ""
fi
if [ "$RUN_FULL" = true ]; then
    echo "  # Full summary"
    echo "  cat ${JOBS_BASE}/sourcegraph_full/*/result.json | jq -s 'map(.trials[].verifier_result.rewards.reward) | {mean: (add/length), count: length}'"
fi
