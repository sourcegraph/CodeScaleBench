#!/bin/bash
# DependEval Benchmark 3-Config Comparison Script
#
# Runs selected DependEval tasks (from selected_benchmark_tasks.json) across 3 configurations:
#   1. Baseline (no MCP)
#   2. MCP-Base (Sourcegraph tools without Deep Search)
#   3. MCP-Full (Sourcegraph + Deep Search hybrid)
#
# Note: DependEval tasks are dependency ordering/multifile editing with code bundled
# in-container (/workspace/code_content.txt). MCP may provide limited benefit.
#
# Usage:
#   ./configs/dependeval_3config.sh [OPTIONS]
#
# Options:
#   --baseline-only        Run only baseline (no MCP)
#   --base-only            Run only MCP-Base
#   --full-only            Run only MCP-Full (sourcegraph_full)
#   --model MODEL          Override model (default: claude-opus-4-5-20251101)
#   --category CATEGORY    Run category (default: official)
#   --parallel N           Number of parallel task subshells (default: 1)
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
TASKS_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks/ccb_dependeval"
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
    if t['benchmark'] == 'ccb_dependeval' and not t.get('excluded', False):
        print(t['task_id'])
")

# Sourcegraph repo name mapping for DependEval tasks
# These are the original GitHub repos the task code was extracted from.
# Note: DependEval tasks bundle all code in-container, so SG search provides
# supplementary context only.
declare -A TASK_SG_REPO_NAMES=(
    # Java - dependency_recognition
    ["dependency_recognition-java-488d70a0"]="github.com/TimotheeJeannin/ProviGen"
    ["dependency_recognition-java-a06aa17b"]="github.com/apache/iceberg"
    ["dependency_recognition-java-a6bb8222"]="github.com/apache/iceberg"
    ["dependency_recognition-java-c7138508"]="github.com/oracle/oracle-r2dbc"
    # Java - multifile_editing
    ["multifile_editing-java-2e96d995"]="github.com/SourceLabOrg/kafka-webview"
    ["multifile_editing-java-5edcbb0d"]="github.com/segler-alex/RadioDroid"
    ["multifile_editing-java-8d0d378a"]="github.com/brettwooldridge/NuProcess"
    ["multifile_editing-java-e1c422ed"]="github.com/msg555/PowerTutor"
    # JavaScript - dependency_recognition
    ["dependency_recognition-javascript-6940aa7b"]="github.com/Alexloof/Next-GraphQL-Blog"
    ["dependency_recognition-javascript-d52503a0"]=""
    ["dependency_recognition-javascript-dafb5116"]="github.com/puzpuzpuz/cls-rtracer"
    ["dependency_recognition-javascript-ef7ab7e5"]="github.com/cnwangjie/better-onetab"
    # JavaScript - multifile_editing
    ["multifile_editing-javascript-460fab96"]="github.com/jaakkos/winston-logstash"
    ["multifile_editing-javascript-86e61c71"]="github.com/alchemyplatform/NFT-Marketplace-Tutorial"
    ["multifile_editing-javascript-beeb2c66"]="github.com/zadvorsky/three.bas"
    ["multifile_editing-javascript-bf306859"]="github.com/tomatau/type-to-reducer"
    # Python - dependency_recognition
    ["dependency_recognition-python-58e6c2b0"]=""
    ["dependency_recognition-python-7c0ee37f"]="github.com/minzwon/semi-supervised-music-tagging-transformer"
    ["dependency_recognition-python-83d51f82"]="github.com/open-cloud/xos"
    ["dependency_recognition-python-bb854fc4"]="github.com/alexa/alexa-apis-for-python"
    # Python - multifile_editing
    ["multifile_editing-python-37688cee"]="github.com/pimoroni/piglow"
    ["multifile_editing-python-6e11aa67"]="github.com/microsoft/Codex-CLI"
    ["multifile_editing-python-85970e74"]="github.com/Pzqqt/Magisk_Manager_Recovery_Tool"
    ["multifile_editing-python-ea840a03"]="github.com/modAL-python/modAL"
    # TypeScript - dependency_recognition
    ["dependency_recognition-typescript-a36bf7a5"]="github.com/International-Slackline-Association/Rankings-Backend"
    ["dependency_recognition-typescript-b512c0c8"]="github.com/wookieb/predicates"
    ["dependency_recognition-typescript-b8647ec9"]=""
    ["dependency_recognition-typescript-d13f8f68"]="github.com/kernel-mod/installer-gui"
    # TypeScript - multifile_editing
    ["multifile_editing-typescript-01b00e0e"]="github.com/akello-io/akello"
    ["multifile_editing-typescript-1469d2cc"]=""
    ["multifile_editing-typescript-4253968d"]=""
    ["multifile_editing-typescript-73e7d1bc"]="github.com/khaosdoctor/event-sourcing-demo-app"
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
JOBS_BASE="runs/${CATEGORY}/dependeval_${MODEL_SHORT}_${TIMESTAMP}"

echo "=============================================="
echo "DependEval 3-Config Benchmark"
echo "=============================================="
echo "Model: ${MODEL}"
echo "Tasks: ${#TASK_IDS[@]}"
echo "Concurrency: ${CONCURRENCY}"
echo "Parallel jobs: ${PARALLEL_JOBS}"
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

    ensure_fresh_token_all

    log_section "Running DependEval - Mode: $mode"

    mkdir -p "$jobs_subdir"

    _dependeval_run_single() {
        local task_id=$1
        local task_home=$2
        local task_path="${TASKS_DIR}/${task_id}"

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
            2>&1 | tee "${jobs_subdir}/${task_id}.log" \
            || {
                echo "WARNING: Task $task_id failed (exit code: $?)"
            }
    }

    run_tasks_parallel TASK_IDS _dependeval_run_single || true

    # Extract metrics for all completed tasks in this mode
    extract_all_metrics "$jobs_subdir" "ccb_dependeval" "$mode"
    validate_and_report "$jobs_subdir" "$mode"

    log_section "Completed DependEval - Mode: $mode"
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
echo "  cat ${JOBS_BASE}/*/*/result.json | jq -r '.trials[].verifier_result.rewards.reward'"
