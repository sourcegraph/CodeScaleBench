#!/bin/bash
# DependEval 9-Task 3-Config Comparison Script
#
# Runs selected DependEval tasks (from selected_benchmark_tasks.json) across 3 configurations:
#   1. Baseline (no MCP)
#   2. MCP-Base (Sourcegraph tools without Deep Search)
#   3. MCP-Full (Sourcegraph + Deep Search hybrid)
#
# Usage:
#   ./configs/dependeval_3config.sh [OPTIONS]
#
# Options:
#   --baseline-only        Run only baseline (no MCP)
#   --base-only   Run only MCP-Base
#   --full-only            Run only MCP-Full (sourcegraph_full)
#   --model MODEL          Override model (default: claude-opus-4-5-20251101)
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
BENCHMARK_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks/ccb_dependeval"
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

# Load task dirs from canonical selection file (DependEval tasks are nested under category subdirs)
SELECTION_FILE="$SCRIPT_DIR/selected_benchmark_tasks.json"
if [ ! -f "$SELECTION_FILE" ]; then
    echo "ERROR: selected_benchmark_tasks.json not found at $SELECTION_FILE"
    echo "Run: python3 scripts/select_benchmark_tasks.py"
    exit 1
fi

readarray -t TASK_DIRS < <(python3 -c "
import json, os
tasks = json.load(open('$SELECTION_FILE'))['tasks']
for t in tasks:
    if t['benchmark'] == 'ccb_dependeval':
        # task_dir is 'ccb_dependeval/DR_java/task_id' -- strip benchmark prefix
        print(os.path.relpath(t['task_dir'], 'ccb_dependeval'))
")

# Sourcegraph repo name mapping for DependEval tasks
# These override SOURCEGRAPH_REPO_NAME so the agent searches the correct repo
# All repos are dormant (last commits 2014-2023); HEAD = correct snapshot
# RC tasks now included - their repos were identified from code_content.txt
declare -A TASK_SG_REPO_NAMES=(
    ["DR_java/dependency_recognition-java-unknown"]="sg-benchmarks/AccountAuthenticator--c01b5a75"
    ["DR_javascript/dependency_recognition-javascript-unknown"]="sg-benchmarks/FitnessApp--2f7897cc"
    ["DR_python/dependency_recognition-python-unknown"]="sg-benchmarks/SRCNN-pytorch--064dbaac"
    ["ME_java/multifile_editing-java-unknown"]="sg-benchmarks/Android-DraggableGridViewPager--7233dbf9"
    ["ME_javascript/multifile_editing-javascript-unknown"]="sg-benchmarks/React-Native-Reflective-UI--3bdf4020"
    ["ME_python/multifile_editing-python-unknown"]="sg-benchmarks/SRCNN-pytorch--064dbaac"
    ["RC_java/repo_construction-java-unknown"]="sg-benchmarks/ProviGen--80c8a202"
    ["RC_javascript/repo_construction-javascript-unknown"]="sg-benchmarks/cypress-plugin-snapshots--a8bd8838"
    ["RC_python/repo_construction-python-unknown"]="sg-benchmarks/katana-skipper--053ef083"
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
JOBS_BASE="runs/${CATEGORY}/dependeval_${MODEL_SHORT}_${TIMESTAMP}"

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

run_task_batch() {
    local mode=$1
    local mcp_type=$2
    local jobs_subdir="${JOBS_BASE}/${mode}"

    log_section "Running DependEval - Mode: $mode"

    echo "Configuration:"
    echo "  Mode: $mode"
    echo "  MCP Type: $mcp_type"
    echo "  Model: $MODEL"
    echo "  Tasks: ${#TASK_DIRS[@]}"
    echo "  Concurrency: $CONCURRENCY"
    echo "  Timeout Multiplier: ${TIMEOUT_MULTIPLIER}x"
    echo "  Jobs directory: $jobs_subdir"
    echo ""

    mkdir -p "$jobs_subdir"

    for task_dir in "${TASK_DIRS[@]}"; do
        local task_path="$BENCHMARK_DIR/$task_dir"

        if [ ! -d "$task_path" ]; then
            echo "ERROR: Task directory not found: $task_path"
            continue
        fi

        echo "Running task: $task_dir ($mode)"

        # Set Sourcegraph repo name override for this task (if mapped)
        local sg_repo="${TASK_SG_REPO_NAMES[$task_dir]:-}"
        if [ -n "$sg_repo" ]; then
            echo "  SOURCEGRAPH_REPO_NAME: $sg_repo"
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
            2>&1 | tee "${jobs_subdir}/$(basename $task_dir).log" \
            || {
                echo "WARNING: Task $task_dir failed (exit code: $?)"
                echo "Continuing with remaining tasks..."
            }

        echo ""
    done

    # Extract metrics for all completed tasks in this mode
    extract_all_metrics "$jobs_subdir" "ccb_dependeval" "$mode"

    log_section "Completed DependEval - Mode: $mode"
}

# ============================================
# MAIN EXECUTION
# ============================================
log_section "DependEval 9-Task 3-Config Benchmark Comparison"
echo "Starting benchmark run..."
echo "  Baseline: $RUN_BASELINE"
echo "  MCP-Base: $RUN_BASE"
echo "  MCP-Full: $RUN_FULL"
echo "  Model: $MODEL"
echo "  Benchmark Directory: $BENCHMARK_DIR"
echo "  Jobs Base: $JOBS_BASE"
echo ""

mkdir -p "$JOBS_BASE"

if [ "$RUN_BASELINE" = true ]; then
    run_task_batch "baseline" "none"
fi

if [ "$RUN_BASE" = true ]; then
    run_task_batch "sourcegraph_base" "sourcegraph_base"
fi

if [ "$RUN_FULL" = true ]; then
    run_task_batch "sourcegraph_full" "sourcegraph_full"
fi

log_section "Benchmark Complete"
echo "Results saved to: $JOBS_BASE"
echo ""
echo "Analyze task results:"
echo "  cat $JOBS_BASE/*/*/result.json | jq -r '.trials[].verifier_result.rewards.reward'"
