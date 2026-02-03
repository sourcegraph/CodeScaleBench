#!/bin/bash
# RepoQA 10-Task 3-Config Comparison Script
#
# Runs selected RepoQA tasks (from selected_benchmark_tasks.json) across 3 configurations:
#   1. Baseline (no MCP)
#   2. MCP-Base (Sourcegraph tools without Deep Search)
#   3. MCP-Full (Sourcegraph + Deep Search hybrid)
#
# Usage:
#   ./configs/repoqa_3config.sh [OPTIONS]
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
TASKS_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks/ccb_repoqa/tasks"
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
    if t['benchmark'] == 'ccb_repoqa':
        print(t['task_id'])
")

# Also read task_dir for correct path resolution (task_id != directory name)
readarray -t TASK_REL_DIRS < <(python3 -c "
import json, os
tasks = json.load(open('$SELECTION_FILE'))['tasks']
for t in tasks:
    if t['benchmark'] == 'ccb_repoqa':
        print(os.path.relpath(t['task_dir'], 'ccb_repoqa/tasks'))
")

# Sourcegraph repo name mapping for RepoQA tasks
# These override SOURCEGRAPH_REPO_NAME so the agent searches the correct repo
declare -A TASK_SG_REPO_NAMES=(
    ["ccb_repoqa-cpp-apache-logging-log4cxx-03"]="sg-benchmarks/apache--logging-log4cxx--502f5711"
    ["ccb_repoqa-cpp-skypjack-uvw-00"]="sg-benchmarks/skypjack--uvw--ba10b276"
    ["ccb_repoqa-java-google-gson-03"]="sg-benchmarks/google--gson--ee61e3f0"
    ["ccb_repoqa-java-square-retrofit-04"]="sg-benchmarks/square--retrofit--10014c2b"
    ["ccb_repoqa-python-psf-black-01"]="sg-benchmarks/psf--black--f03ee113"
    ["ccb_repoqa-python-python-poetry-poetry-08"]="sg-benchmarks/python-poetry--poetry--21ffd992"
    ["ccb_repoqa-rust-rust-bakery-nom-06"]="sg-benchmarks/rust-bakery--nom--e87c7da9"
    ["ccb_repoqa-rust-helix-editor-helix-03"]="sg-benchmarks/helix-editor--helix--e69292e5"
    ["ccb_repoqa-typescript-xenova-transformers.js-08"]="sg-benchmarks/xenova--transformers.js--64274313"
    ["ccb_repoqa-typescript-expressjs-express-07"]="sg-benchmarks/expressjs--express--815f7993"
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
JOBS_BASE="runs/${CATEGORY}/repoqa_${MODEL_SHORT}_${TIMESTAMP}"

echo "=============================================="
echo "RepoQA 10-Task 3-Config Benchmark"
echo "=============================================="
echo "Model: ${MODEL}"
echo "Tasks: ${#TASK_IDS[@]}"
echo "Concurrency: ${CONCURRENCY}"
echo "Jobs directory: ${JOBS_BASE}"
echo "Run baseline: ${RUN_BASELINE}"
echo "Run MCP-Base: ${RUN_BASE}"
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

run_task_batch() {
    local mode=$1
    local mcp_type=$2
    local jobs_subdir="${JOBS_BASE}/${mode}"

    ensure_fresh_token

    log_section "Running RepoQA - Mode: $mode"

    mkdir -p "$jobs_subdir"

    local idx=0
    for task_id in "${TASK_IDS[@]}"; do
        local task_path="${TASKS_DIR}/${TASK_REL_DIRS[$idx]}"
        idx=$((idx + 1))

        if [ ! -d "$task_path" ]; then
            echo "ERROR: Task directory not found: $task_path"
            continue
        fi

        echo "Running task: $task_id ($mode)"

        # Set Sourcegraph repo name override for this task (if mapped)
        local sg_repo="${TASK_SG_REPO_NAMES[$task_id]:-}"
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
            2>&1 | tee "${jobs_subdir}/${task_id}.log" \
            || {
                echo "WARNING: Task $task_id failed (exit code: $?)"
                echo "Continuing with remaining tasks..."
            }

        echo ""
    done

    # Extract metrics for all completed tasks in this mode
    extract_all_metrics "$jobs_subdir" "ccb_repoqa" "$mode"
    validate_and_report "$jobs_subdir" "$mode"

    log_section "Completed RepoQA - Mode: $mode"
}

# ============================================
# MAIN EXECUTION
# ============================================
if [ "$RUN_BASELINE" = true ]; then
    run_task_batch "baseline" "none"
fi

if [ "$RUN_BASE" = true ]; then
    run_task_batch "sourcegraph_base" "sourcegraph_base"
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
echo "  cat ${JOBS_BASE}/*/*/result.json | jq -r '.verifier_result.rewards | .reward // .score'"
