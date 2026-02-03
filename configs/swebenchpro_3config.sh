#!/bin/bash
# SWE-bench Pro 3-Config Comparison Script
#
# Runs selected SWE-bench Pro instances (from selected_benchmark_tasks.json) across 3 configurations:
#   1. Baseline (no MCP)
#   2. MCP-Base (Sourcegraph tools without Deep Search)
#   3. MCP-Full (Sourcegraph + Deep Search hybrid)
#
# Usage:
#   ./configs/swebenchpro_3config.sh [OPTIONS]
#
# Options:
#   --baseline-only        Run only baseline (no MCP)
#   --base-only   Run only MCP-Base
#   --full-only            Run only MCP-Full (sourcegraph_full)
#   --model MODEL          Override model (default: claude-opus-4-5-20251101)
#   --concurrency N        Number of concurrent tasks (default: 2)
#   --category CATEGORY    Run category (default: official)
#
# Prerequisites:
#   - ~/evals/.env.local with ANTHROPIC_API_KEY (required)
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

ensure_fresh_token

# ============================================
# CONFIGURATION
# ============================================
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
MODEL="${MODEL:-anthropic/claude-opus-4-5-20251101}"
CONCURRENCY=2
TIMEOUT_MULTIPLIER=10
RUN_BASELINE=true
RUN_BASE=true
RUN_FULL=true
CATEGORY="${CATEGORY:-official}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --baseline-only)
            RUN_BASE=false
            RUN_FULL=false
            shift
            ;;
        --base-only)
            RUN_BASELINE=false
            RUN_FULL=false
            shift
            ;;
        --full-only)
            RUN_BASELINE=false
            RUN_BASE=false
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
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Check MCP credentials if MCP modes requested
if { [ "$RUN_BASE" = true ] || [ "$RUN_FULL" = true ]; } && [ -z "$SOURCEGRAPH_ACCESS_TOKEN" ]; then
    echo "WARNING: MCP modes requested but SOURCEGRAPH_ACCESS_TOKEN not set"
    echo "Skipping MCP runs. Use --baseline-only to suppress this warning."
    RUN_BASE=false
    RUN_FULL=false
fi

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
echo "SWE-bench Pro 3-Config Benchmark"
echo "=============================================="
echo "Model: ${MODEL}"
echo "Tasks: ${#TASK_IDS[@]}"
echo "Concurrency: ${CONCURRENCY}"
echo "Timeout multiplier: ${TIMEOUT_MULTIPLIER}x"
echo "Jobs directory: ${JOBS_BASE}"
echo "Run baseline: ${RUN_BASELINE}"
echo "Run MCP-Base: ${RUN_BASE}"
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

# Build SOURCEGRAPH_REPO_NAME for swebenchpro tasks.
# Parses task_id to derive the sg-benchmarks repo name.
get_swebench_sg_repo() {
    local task_id=$1
    local sg_repo
    sg_repo=$(python3 -c "
import re, sys
tid = '$task_id'
# SWE-bench Pro task_id format: instance_{org}__{repo}-{commit40hex}[-vXXX]
# or: {org}__{repo}-{commit40hex}
m = re.match(r'(?:instance_)?(.+?)__(.+?)-([a-f0-9]{7,40})', tid)
if m:
    org = m.group(1).replace('__','/')
    repo = m.group(2)
    commit = m.group(3)[:8]
    print(f'{org}--{repo}--{commit}')
" 2>/dev/null)

    if [ -n "$sg_repo" ]; then
        echo "sg-benchmarks/$sg_repo"
    else
        echo ""
    fi
}

# Run MCP mode tasks one-by-one so SOURCEGRAPH_REPO_NAME can be set per task
run_swebench_mcp_task_batch() {
    local mode=$1
    local mcp_type=$2
    local jobs_subdir="${JOBS_BASE}/${mode}"
    ensure_fresh_token
    mkdir -p "$jobs_subdir"
    for task_id in "${TASK_IDS[@]}"; do
        local sg_repo=$(get_swebench_sg_repo "$task_id")
        if [ -n "$sg_repo" ]; then
            export SOURCEGRAPH_REPO_NAME="$sg_repo"
            echo "  [${mode}] Task ${task_id} -> SOURCEGRAPH_REPO_NAME=${sg_repo}"
        else
            unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
            echo "  [${mode}] Task ${task_id} -> no SG repo mapping (could not parse task_id)"
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
    done
    unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
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
# RUN MCP-Base (sourcegraph_base)
# Per-task iteration to set SOURCEGRAPH_REPO_NAME for indexed repos
# ============================================
if [ "$RUN_BASE" = true ]; then
    echo ""
    echo "[MCP-Base] Starting per-task MCP-Base run..."
    echo ""

    run_swebench_mcp_task_batch "sourcegraph_base" "sourcegraph_base"
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
if [ "$RUN_BASE" = true ]; then
    echo "  # MCP-Base - count resolved"
    echo "  cat ${JOBS_BASE}/sourcegraph_base/*/result.json | jq -s '[.[] | select(.trials[].verifier_result.resolved == true)] | length'"
    echo ""
fi
if [ "$RUN_FULL" = true ]; then
    echo "  # MCP-Full - count resolved"
    echo "  cat ${JOBS_BASE}/sourcegraph_full/*/result.json | jq -s '[.[] | select(.trials[].verifier_result.resolved == true)] | length'"
fi
