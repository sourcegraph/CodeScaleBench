#!/bin/bash
# Big Code MCP 4-Task 3-Config Comparison Script
#
# Runs all 4 big code MCP tasks across 3 configurations:
#   1. Baseline (no MCP)
#   2. MCP-NoDeepSearch (Sourcegraph MCP without deep search)
#   3. MCP-Full (Sourcegraph MCP + deep search)
#
# Usage:
#   ./configs/bigcode_3config.sh [options]
#
# Options:
#   --baseline-only        Run only baseline (no MCP)
#   --no-deepsearch-only   Run only MCP-NoDeepSearch
#   --full-only            Run only MCP-Full (sourcegraph_hybrid)
#   --model MODEL          Override model (default: claude-opus-4-5-20251101)
#   --category CATEGORY    Override run category (default: official)
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
BENCHMARK_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks/big_code_mcp"
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
MODEL="${MODEL:-anthropic/claude-opus-4-5-20251101}"
CONCURRENCY=1  # Big codebases - run serially
TIMEOUT_MULTIPLIER=10  # 10x default timeout for large repos
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

# All 4 big code MCP task directories
TASK_DIRS=(
    "big-code-k8s-001"      # Kubernetes: NoScheduleNoTraffic taint (Go, 1.4GB)
    "big-code-servo-001"    # Servo: scrollend DOM event (Rust)
    "big-code-trt-001"      # TensorRT implementation (C++)
    "big-code-vsc-001"      # VS Code feature (TypeScript)
)

# Sourcegraph repo name mapping for Big Code tasks
# These override SOURCEGRAPH_REPO_NAME so the agent searches the correct repo
declare -A TASK_SG_REPO_NAMES=(
    ["big-code-k8s-001"]="sg-benchmarks/kubernetes--latest"
    ["big-code-servo-001"]="sg-benchmarks/servo--latest"
    ["big-code-trt-001"]="sg-benchmarks/TensorRT--latest"
    ["big-code-vsc-001"]="sg-benchmarks/vscode--latest"
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
JOBS_BASE="runs/${CATEGORY}/bigcode_mcp_${MODEL_SHORT}_${TIMESTAMP}"

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

run_task_batch() {
    local mode=$1
    local mcp_type=$2
    local jobs_subdir="${JOBS_BASE}/${mode}"

    log_section "Running Big Code MCP - Mode: $mode"

    echo "Configuration:"
    echo "  Mode: $mode"
    echo "  MCP Type: $mcp_type"
    echo "  Model: $MODEL"
    echo "  Tasks: ${#TASK_DIRS[@]}"
    echo "  Concurrency: $CONCURRENCY"
    echo "  Timeout Multiplier: ${TIMEOUT_MULTIPLIER}x"
    echo "  Jobs directory: $jobs_subdir"
    echo ""

    # Create jobs subdirectory
    mkdir -p "$jobs_subdir"

    # Run each task individually (since they're in separate directories)
    for task_dir in "${TASK_DIRS[@]}"; do
        local task_path="$BENCHMARK_DIR/$task_dir"

        if [ ! -d "$task_path" ]; then
            echo "ERROR: Task directory not found: $task_path"
            continue
        fi

        echo "Running task: $task_dir ($mode)"
        echo "  Path: $task_path"

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
            2>&1 | tee "${jobs_subdir}/${task_dir}.log" \
            || {
                echo "WARNING: Task $task_dir failed (exit code: $?)"
                echo "Continuing with remaining tasks..."
            }

        echo ""
    done

    log_section "Completed Big Code MCP - Mode: $mode"
    echo "Job results: $jobs_subdir"
    echo ""
}

# ============================================
# MAIN EXECUTION
# ============================================
log_section "Big Code MCP 3-Config Benchmark Comparison"
echo "Starting benchmark run..."
echo "  Baseline: $RUN_BASELINE"
echo "  MCP-NoDeepSearch: $RUN_NO_DEEPSEARCH"
echo "  MCP-Full: $RUN_FULL"
echo "  Model: $MODEL"
echo "  Benchmark Directory: $BENCHMARK_DIR"
echo "  Jobs Base: $JOBS_BASE"
echo ""

# Create jobs base directory
mkdir -p "$JOBS_BASE"

# Run baseline (no MCP)
if [ "$RUN_BASELINE" = true ]; then
    run_task_batch "baseline" "none"
fi

# Run MCP-NoDeepSearch (Sourcegraph MCP without deep search)
if [ "$RUN_NO_DEEPSEARCH" = true ]; then
    run_task_batch "sourcegraph_no_deepsearch" "sourcegraph_no_deepsearch"
fi

# Run MCP-Full (Sourcegraph MCP + deep search)
if [ "$RUN_FULL" = true ]; then
    run_task_batch "sourcegraph_hybrid" "sourcegraph_hybrid"
fi

# ============================================
# SUMMARY
# ============================================
log_section "Benchmark Complete"
echo "Results saved to: $JOBS_BASE"
echo ""
echo "View results:"
if [ "$RUN_BASELINE" = true ]; then
    echo "  # Baseline summary"
    echo "  ls -la $JOBS_BASE/baseline/"
    echo ""
fi
if [ "$RUN_NO_DEEPSEARCH" = true ]; then
    echo "  # MCP-NoDeepSearch summary"
    echo "  ls -la $JOBS_BASE/sourcegraph_no_deepsearch/"
    echo ""
fi
if [ "$RUN_FULL" = true ]; then
    echo "  # MCP-Full summary"
    echo "  ls -la $JOBS_BASE/sourcegraph_hybrid/"
    echo ""
fi
echo ""
echo "Analyze task results:"
echo "  cat $JOBS_BASE/*/*/result.json | jq -r '.trials[].verifier_result.rewards.reward'"
echo ""
echo "Expected observations:"
echo "  - Baseline: Slower codebase exploration, may miss patterns"
echo "  - MCP-NoDeepSearch: Fast keyword + NLS search, no deep reasoning"
echo "  - MCP-Full: Deep semantic search + architectural understanding"
echo ""
