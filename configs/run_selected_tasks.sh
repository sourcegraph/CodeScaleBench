#!/bin/bash
# Unified Benchmark Runner — Reads tasks from selected_benchmark_tasks.json
#
# Runs selected benchmark tasks across 3 MCP configurations:
#   1. Baseline (no MCP)
#   2. MCP-Base (Sourcegraph tools without Deep Search)
#   3. MCP-Full (Sourcegraph + Deep Search)
#
# This script replaces the per-benchmark *_3config.sh scripts by reading
# the canonical task selection from selected_benchmark_tasks.json.
#
# Usage:
#   ./configs/run_selected_tasks.sh [OPTIONS]
#
# Options:
#   --benchmark BENCHMARK  Run only this benchmark (e.g., ccb_swebenchpro, ccb_locobench)
#   --baseline-only        Run only baseline (no MCP)
#   --base-only            Run only MCP-Base (sourcegraph_base)
#   --full-only            Run only MCP-Full (sourcegraph_full)
#   --model MODEL          Override model (default: claude-opus-4-5-20251101)
#   --concurrency N        Concurrent tasks (default: 2)
#   --category CATEGORY    Run category (default: official)
#   --skip-completed       Skip tasks that already have result.json + task_metrics.json
#   --dry-run              Print tasks without running
#
# Prerequisites:
#   - configs/selected_benchmark_tasks.json in repo
#   - ~/evals/.env.local with ANTHROPIC_API_KEY
#   - SOURCEGRAPH_ACCESS_TOKEN in .env.local (for MCP modes)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
cd "$REPO_ROOT"

# Agent module lives in the evals repo; add it to PYTHONPATH
AGENT_DIR="${AGENT_DIR:-$HOME/evals/custom_agents/agents/claudecode}"
export PYTHONPATH="${AGENT_DIR}:$(pwd):$PYTHONPATH"

# Shared config: subscription mode + token refresh
source "$SCRIPT_DIR/_common.sh"

SELECTION_FILE="$REPO_ROOT/configs/selected_benchmark_tasks.json"

# ============================================
# PARSE ARGUMENTS
# ============================================
BENCHMARK_FILTER=""
MODEL="${MODEL:-anthropic/claude-opus-4-5-20251101}"
CONCURRENCY=2
TIMEOUT_MULTIPLIER=10
RUN_BASELINE=true
RUN_BASE=true
RUN_FULL=true
CATEGORY="${CATEGORY:-official}"
DRY_RUN=false
SKIP_COMPLETED=false
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"

while [[ $# -gt 0 ]]; do
    case $1 in
        --benchmark)
            BENCHMARK_FILTER="$2"
            shift 2
            ;;
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
        --skip-completed)
            SKIP_COMPLETED=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# ============================================
# VERIFY PREREQUISITES
# ============================================
if [ ! -f "$SELECTION_FILE" ]; then
    echo "ERROR: selected_benchmark_tasks.json not found at $SELECTION_FILE"
    echo "Run: python3 scripts/select_benchmark_tasks.py"
    exit 1
fi

if [ -f ~/evals/.env.local ]; then
    source ~/evals/.env.local
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: ANTHROPIC_API_KEY is not set"
    exit 1
fi

if { [ "$RUN_BASE" = true ] || [ "$RUN_FULL" = true ]; } && [ -z "$SOURCEGRAPH_ACCESS_TOKEN" ]; then
    echo "WARNING: MCP modes requested but SOURCEGRAPH_ACCESS_TOKEN not set"
    echo "Skipping MCP runs."
    RUN_BASE=false
    RUN_FULL=false
fi

ensure_fresh_token

# ============================================
# EXTRACT TASKS FROM SELECTION FILE
# ============================================
# Python helper to extract task info grouped by benchmark
extract_tasks() {
    python3 -c "
import json, sys

selection = json.load(open('$SELECTION_FILE'))
benchmark_filter = '$BENCHMARK_FILTER'

for task in selection['tasks']:
    bm = task['benchmark']
    if benchmark_filter and bm != benchmark_filter:
        continue
    task_dir = 'benchmarks/' + task['task_dir']
    print(f'{bm}\t{task[\"task_id\"]}\t{task_dir}')
"
}

# Read tasks into arrays grouped by benchmark, storing both task_ids and task_dirs
declare -A BENCHMARK_TASK_IDS
declare -A BENCHMARK_TASK_DIRS
declare -A BENCHMARK_COUNTS

while IFS=$'\t' read -r bm task_id task_dir; do
    BENCHMARK_TASK_IDS[$bm]+="${task_id}"$'\n'
    BENCHMARK_TASK_DIRS[$bm]+="${task_dir}"$'\n'
    BENCHMARK_COUNTS[$bm]=$(( ${BENCHMARK_COUNTS[$bm]:-0} + 1 ))
done < <(extract_tasks)

if [ ${#BENCHMARK_COUNTS[@]} -eq 0 ]; then
    echo "ERROR: No tasks found"
    if [ -n "$BENCHMARK_FILTER" ]; then
        echo "  Filter: --benchmark $BENCHMARK_FILTER"
    fi
    exit 1
fi

# ============================================
# SUMMARY
# ============================================
_model_lower=$(echo "$MODEL" | awk -F/ '{print $NF}' | tr '[:upper:]' '[:lower:]')
case "$_model_lower" in
    *opus*)   MODEL_SHORT="opus" ;;
    *sonnet*) MODEL_SHORT="sonnet" ;;
    *haiku*)  MODEL_SHORT="haiku" ;;
    *)        MODEL_SHORT=$(echo "$_model_lower" | tr -d '-' | tr -d '_' | cut -c1-8) ;;
esac

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TOTAL_TASKS=0
for bm in "${!BENCHMARK_COUNTS[@]}"; do
    TOTAL_TASKS=$(( TOTAL_TASKS + ${BENCHMARK_COUNTS[$bm]} ))
done

echo "=============================================="
echo "CodeContextBench Selected Tasks Runner"
echo "=============================================="
echo "Source:        $SELECTION_FILE"
echo "Model:         $MODEL"
echo "Total tasks:   $TOTAL_TASKS"
echo "Concurrency:   $CONCURRENCY"
echo "Configs:       baseline=$RUN_BASELINE sourcegraph_base=$RUN_BASE sourcegraph_full=$RUN_FULL"
echo "Skip done:     $SKIP_COMPLETED"
echo ""
echo "Tasks per benchmark:"
for bm in $(echo "${!BENCHMARK_COUNTS[@]}" | tr ' ' '\n' | sort); do
    printf "  %-25s %d\n" "$bm" "${BENCHMARK_COUNTS[$bm]}"
done
echo ""

if [ "$DRY_RUN" = true ]; then
    echo "[DRY RUN] Would run these tasks:"
    for bm in $(echo "${!BENCHMARK_TASK_DIRS[@]}" | tr ' ' '\n' | sort); do
        echo ""
        echo "=== $bm (${BENCHMARK_COUNTS[$bm]} tasks) ==="
        echo "${BENCHMARK_TASK_IDS[$bm]}" | grep -v '^$' | head -5
        count=${BENCHMARK_COUNTS[$bm]}
        if [ "$count" -gt 5 ]; then
            echo "  ... and $(( count - 5 )) more"
        fi
    done
    exit 0
fi

# ============================================
# HELPER FUNCTIONS
# ============================================

# Resolve SOURCEGRAPH_REPO_NAME for a locobench task from docker-compose.yaml
get_sg_repo_name() {
    local task_dir=$1
    local dc_file="${task_dir}/environment/docker-compose.yaml"
    if [ -f "$dc_file" ]; then
        local proj_id
        proj_id=$(grep 'LOCOBENCH_PROJECT_ID=' "$dc_file" | head -1 | sed 's/.*LOCOBENCH_PROJECT_ID=//')
        if [ -n "$proj_id" ]; then
            echo "sg-benchmarks/locobench-${proj_id}"
            return
        fi
    fi
    echo ""
}

# Resolve SOURCEGRAPH_REPO_NAME for a swebenchpro task from its task_id
get_swebench_sg_repo() {
    local task_id=$1
    local sg_repo
    sg_repo=$(python3 -c "
import re
tid = '$task_id'
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

# Extract per-task metrics for Dashboard
extract_all_metrics() {
    local jobs_dir=$1
    local benchmark=$2
    local config=$3
    echo "Extracting per-task metrics from $jobs_dir..."
    for result_dir in "$jobs_dir"/*/*/; do
        if [ -f "$result_dir/result.json" ] && [ ! -f "$result_dir/task_metrics.json" ]; then
            python3 "$REPO_ROOT/scripts/extract_task_metrics.py" \
                --task-dir "$result_dir" \
                --benchmark "$benchmark" \
                --config "$config" \
                --selected-tasks "$SELECTION_FILE" \
                2>&1 || echo "  WARNING: metrics extraction failed for $(basename "$result_dir")"
        fi
    done
}

# Check if a task is already completed (has result.json + task_metrics.json)
is_task_completed() {
    local jobs_dir=$1
    local task_id=$2
    if [ "$SKIP_COMPLETED" != true ]; then
        return 1  # Not skipping
    fi
    # Check if any subdirectory matching this task has both files
    for dir in "$jobs_dir"/*/*"${task_id:0:30}"*/; do
        if [ -f "$dir/result.json" ] && [ -f "$dir/task_metrics.json" ]; then
            return 0  # Completed
        fi
    done
    return 1  # Not completed
}

# ============================================
# RUN FUNCTION — handles both path-based and dataset-based benchmarks
# ============================================
run_benchmark() {
    local bm=$1
    local mcp_mode=$2
    local mcp_type=$3

    local jobs_dir="runs/${CATEGORY}/${bm}_${MODEL_SHORT}_${TIMESTAMP}/${mcp_mode}"
    mkdir -p "$jobs_dir"

    echo ""
    echo "[${mcp_mode}] Running ${BENCHMARK_COUNTS[$bm]} ${bm} tasks..."

    # Get task IDs and directories for this benchmark
    local task_ids task_dirs
    task_ids=$(echo "${BENCHMARK_TASK_IDS[$bm]}" | grep -v '^$')
    task_dirs=$(echo "${BENCHMARK_TASK_DIRS[$bm]}" | grep -v '^$')

    # Iterate over tasks using parallel arrays
    local idx=0
    while IFS= read -r task_id && IFS= read -r task_path <&3; do
        [ -z "$task_id" ] && continue
        idx=$((idx + 1))

        # Skip completed tasks if requested
        if is_task_completed "$jobs_dir" "$task_id"; then
            echo "  [${mcp_mode}] SKIP (completed): $task_id"
            continue
        fi

        local abs_path="$REPO_ROOT/$task_path"

        # Set SOURCEGRAPH_REPO_NAME for MCP modes
        if [ "$mcp_type" != "none" ]; then
            local sg_repo=""
            if [ "$bm" = "ccb_locobench" ]; then
                sg_repo=$(get_sg_repo_name "$abs_path")
            elif [ "$bm" = "ccb_swebenchpro" ]; then
                sg_repo=$(get_swebench_sg_repo "$task_id")
            fi
            if [ -n "$sg_repo" ]; then
                export SOURCEGRAPH_REPO_NAME="$sg_repo"
                echo "  [${mcp_mode}] ($idx/${BENCHMARK_COUNTS[$bm]}) $task_id -> SG_REPO=${sg_repo}"
            else
                unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
                echo "  [${mcp_mode}] ($idx/${BENCHMARK_COUNTS[$bm]}) $task_id -> no SG repo mapping"
            fi
        else
            unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
            echo "  [${mcp_mode}] ($idx/${BENCHMARK_COUNTS[$bm]}) $task_id"
        fi

        # swebenchpro uses --dataset mode; all others use --path
        if [ "$bm" = "ccb_swebenchpro" ]; then
            BASELINE_MCP_TYPE=$mcp_type harbor run \
                --dataset swebenchpro \
                -t "$task_id" \
                --agent-import-path "$AGENT_PATH" \
                --model "$MODEL" \
                --jobs-dir "$jobs_dir" \
                -n $CONCURRENCY \
                --timeout-multiplier $TIMEOUT_MULTIPLIER \
                2>&1 | tee -a "${jobs_dir}.log" \
                || echo "WARNING: Task failed: $task_id (continuing...)"
        else
            if [ ! -d "$abs_path" ]; then
                echo "WARNING: Task directory not found: $abs_path"
                continue
            fi
            BASELINE_MCP_TYPE=$mcp_type harbor run \
                --path "$abs_path" \
                --agent-import-path "$AGENT_PATH" \
                --model "$MODEL" \
                --jobs-dir "$jobs_dir" \
                -n $CONCURRENCY \
                --timeout-multiplier $TIMEOUT_MULTIPLIER \
                2>&1 | tee -a "${jobs_dir}.log" \
                || echo "WARNING: Task failed: $task_id (continuing...)"
        fi
    done <<< "$task_ids" 3<<< "$task_dirs"

    unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true

    # Extract per-task metrics
    extract_all_metrics "$jobs_dir" "$bm" "$mcp_mode"
}

# ============================================
# MAIN EXECUTION
# ============================================
for bm in $(echo "${!BENCHMARK_COUNTS[@]}" | tr ' ' '\n' | sort); do
    if [ "$RUN_BASELINE" = true ]; then
        run_benchmark "$bm" "baseline" "none"
    fi
    if [ "$RUN_BASE" = true ]; then
        run_benchmark "$bm" "sourcegraph_base" "sourcegraph_base"
    fi
    if [ "$RUN_FULL" = true ]; then
        run_benchmark "$bm" "sourcegraph_full" "sourcegraph_full"
    fi
done

echo ""
echo "=============================================="
echo "All Benchmarks Complete!"
echo "=============================================="
echo "Results: runs/${CATEGORY}/"
echo ""
echo "Generate report:"
echo "  python3 scripts/generate_eval_report.py --selected-tasks configs/selected_benchmark_tasks.json"
