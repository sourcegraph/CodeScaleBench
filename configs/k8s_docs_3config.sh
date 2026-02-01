#!/bin/bash
# Kubernetes Docs 5-Task 3-Config Comparison Script
#
# Runs all 5 Kubernetes documentation tasks across 3 configurations:
#   1. Baseline (no MCP)
#   2. MCP-NoDeepSearch (Sourcegraph tools without Deep Search)
#   3. MCP-Full (Sourcegraph + Deep Search hybrid)
#
# Usage:
#   ./configs/k8s_docs_3config.sh [OPTIONS]
#
# Options:
#   --baseline-only        Run only baseline (no MCP)
#   --no-deepsearch-only   Run only MCP-NoDeepSearch
#   --full-only            Run only MCP-Full (sourcegraph_hybrid)
#   --model MODEL          Override model (default: claude-opus-4-5-20251101)
#   --category CATEGORY    Run category (default: official)
#
# Prerequisites:
#   - ~/evals/.env.local with ANTHROPIC_API_KEY (required)
#   - SOURCEGRAPH_ACCESS_TOKEN in .env.local (required for MCP modes)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# Add claudecode directory to PYTHONPATH for agent imports
export PYTHONPATH="$(pwd):$PYTHONPATH"

# ============================================
# LOAD CREDENTIALS
# ============================================
if [ -f ~/evals/.env.local ]; then
    echo "Loading credentials from ~/evals/.env.local..."
    source ~/evals/.env.local
else
    echo "Warning: ~/evals/.env.local not found"
    echo "Please create it with at minimum:"
    echo "  export ANTHROPIC_API_KEY=\"your-api-key\""
    echo ""
fi

# Verify required credentials
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: ANTHROPIC_API_KEY is not set"
    echo ""
    echo "Please set it in ~/evals/.env.local:"
    echo "  export ANTHROPIC_API_KEY=\"your-api-key\""
    exit 1
fi

echo "ANTHROPIC_API_KEY: set (${#ANTHROPIC_API_KEY} chars)"
if [ -n "$SOURCEGRAPH_ACCESS_TOKEN" ]; then
    echo "SOURCEGRAPH_ACCESS_TOKEN: set (${#SOURCEGRAPH_ACCESS_TOKEN} chars)"
else
    echo "SOURCEGRAPH_ACCESS_TOKEN: not set"
fi
echo ""

# ============================================
# CONFIGURATION
# ============================================
TASKS_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks/kubernetes_docs"
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
MODEL="${MODEL:-anthropic/claude-opus-4-5-20251101}"
CONCURRENCY=2
TIMEOUT_MULTIPLIER=3  # 3x default for 900s task timeout
RUN_BASELINE=true
RUN_NO_DEEPSEARCH=true
RUN_FULL=true
CATEGORY="${CATEGORY:-official}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --baseline-only)
            RUN_NO_DEEPSEARCH=false
            RUN_FULL=false
            shift
            ;;
        --no-deepsearch-only)
            RUN_BASELINE=false
            RUN_FULL=false
            shift
            ;;
        --full-only)
            RUN_BASELINE=false
            RUN_NO_DEEPSEARCH=false
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
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Check MCP credentials if MCP modes requested
if { [ "$RUN_NO_DEEPSEARCH" = true ] || [ "$RUN_FULL" = true ]; } && [ -z "$SOURCEGRAPH_ACCESS_TOKEN" ]; then
    echo "WARNING: MCP modes requested but SOURCEGRAPH_ACCESS_TOKEN not set"
    echo "Skipping MCP runs. Use --baseline-only to suppress this warning."
    RUN_NO_DEEPSEARCH=false
    RUN_FULL=false
fi

# All 5 K8s Docs task IDs
TASK_IDS=(
    "pkg-doc-001"
    "client-go-doc-001"
    "applyconfig-doc-001"
    "apiserver-doc-001"
    "fairqueuing-doc-001"
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
JOBS_BASE="runs/${CATEGORY}/k8s_docs_${MODEL_SHORT}_${TIMESTAMP}"

echo "=============================================="
echo "Kubernetes Docs 5-Task 3-Config Benchmark"
echo "=============================================="
echo "Model: ${MODEL}"
echo "Tasks: ${#TASK_IDS[@]}"
echo "Concurrency: ${CONCURRENCY}"
echo "Jobs directory: ${JOBS_BASE}"
echo "Run baseline: ${RUN_BASELINE}"
echo "Run MCP-NoDeepSearch: ${RUN_NO_DEEPSEARCH}"
echo "Run MCP-Full: ${RUN_FULL}"
echo ""

# Create task list file for Harbor
TASK_LIST_FILE="${JOBS_BASE}/task_list.txt"
mkdir -p "${JOBS_BASE}"

for task_id in "${TASK_IDS[@]}"; do
    echo "${TASKS_DIR}/${task_id}" >> "${TASK_LIST_FILE}"
done

# ============================================
# RUN BASELINE (no MCP)
# ============================================
if [ "$RUN_BASELINE" = true ]; then
    echo ""
    echo "[BASELINE] Starting 5-task baseline run..."
    echo ""

    BASELINE_MCP_TYPE=none harbor run \
        --path "${TASKS_DIR}" \
        --task-name "*" \
        --agent-import-path "${AGENT_PATH}" \
        --model "${MODEL}" \
        --jobs-dir "${JOBS_BASE}/baseline" \
        -n ${CONCURRENCY} \
        --timeout-multiplier ${TIMEOUT_MULTIPLIER} \
        2>&1 | tee "${JOBS_BASE}/baseline.log"
fi

# ============================================
# RUN MCP-NoDeepSearch (sourcegraph_no_deepsearch)
# ============================================
if [ "$RUN_NO_DEEPSEARCH" = true ]; then
    echo ""
    echo "[MCP-NoDeepSearch] Starting 5-task MCP-NoDeepSearch run..."
    echo ""

    BASELINE_MCP_TYPE=sourcegraph_no_deepsearch harbor run \
        --path "${TASKS_DIR}" \
        --task-name "*" \
        --agent-import-path "${AGENT_PATH}" \
        --model "${MODEL}" \
        --jobs-dir "${JOBS_BASE}/sourcegraph_no_deepsearch" \
        -n ${CONCURRENCY} \
        --timeout-multiplier ${TIMEOUT_MULTIPLIER} \
        2>&1 | tee "${JOBS_BASE}/sourcegraph_no_deepsearch.log"
fi

# ============================================
# RUN MCP-Full (sourcegraph_hybrid)
# ============================================
if [ "$RUN_FULL" = true ]; then
    echo ""
    echo "[MCP-Full] Starting 5-task MCP-Full run..."
    echo ""

    BASELINE_MCP_TYPE=sourcegraph_hybrid harbor run \
        --path "${TASKS_DIR}" \
        --task-name "*" \
        --agent-import-path "${AGENT_PATH}" \
        --model "${MODEL}" \
        --jobs-dir "${JOBS_BASE}/sourcegraph_hybrid" \
        -n ${CONCURRENCY} \
        --timeout-multiplier ${TIMEOUT_MULTIPLIER} \
        2>&1 | tee "${JOBS_BASE}/sourcegraph_hybrid.log"
fi

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
if [ "$RUN_NO_DEEPSEARCH" = true ]; then
    echo "  # MCP-NoDeepSearch summary"
    echo "  cat ${JOBS_BASE}/sourcegraph_no_deepsearch/*/result.json | jq -s 'map(.trials[].verifier_result.rewards.reward) | {mean: (add/length), count: length}'"
    echo ""
fi
if [ "$RUN_FULL" = true ]; then
    echo "  # MCP-Full summary"
    echo "  cat ${JOBS_BASE}/sourcegraph_hybrid/*/result.json | jq -s 'map(.trials[].verifier_result.rewards.reward) | {mean: (add/length), count: length}'"
fi
