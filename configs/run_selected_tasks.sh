#!/bin/bash
# Unified Benchmark Runner — Reads tasks from selected_benchmark_tasks.json
#
# Runs selected benchmark tasks across 2 MCP configurations:
#   1. Baseline (no MCP)
#   2. MCP-Full (Sourcegraph + Deep Search)
#
# This script reads the canonical task selection from selected_benchmark_tasks.json
# and runs each task through Harbor with the specified configuration(s).
#
# Usage:
#   ./configs/run_selected_tasks.sh [OPTIONS]
#
# Options:
#   --benchmark BENCHMARK           Run only this benchmark (e.g., ccb_build, ccb_fix)
#   --selection-file PATH           Use alternate selection file (default: selected_benchmark_tasks.json)
#   --use-case-category CATEGORY    Filter by MCP-unique use case category (A-J), only valid with --selection-file
#   --baseline-only                 Run only baseline (no MCP)
#   --full-only                     Run only MCP-Full (mcp-remote-direct)
#   --full-config CONFIG            Full config name (default: mcp-remote-direct)
#                                   Use mcp-remote-artifact for artifact-based evaluation
#   --model MODEL                   Override model (default: claude-opus-4-6)
#   --concurrency N                 Trials per task via harbor -n (default: 1)
#   --parallel N                    Parallel task slots (default: 1). Set to 8 for multi-account runs.
#   --category CATEGORY             Run category (default: staging)
#   --skip-completed                Skip tasks that already have result.json + task_metrics.json
#   --dry-run                       Print tasks without running
#   --yes                           Skip confirmation prompt (non-interactive mode)
#
# Prerequisites:
#   - configs/selected_benchmark_tasks.json in repo (or --selection-file path)
#   - .env.local (repo root) with USE_SUBSCRIPTION=true
#   - SOURCEGRAPH_ACCESS_TOKEN in .env.local (for MCP modes)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
cd "$REPO_ROOT"

# Agent code lives in-repo under agents/
export PYTHONPATH="$(pwd):${PYTHONPATH:-}"

# Shared config: subscription mode + token refresh
source "$SCRIPT_DIR/_common.sh"

SELECTION_FILE="$REPO_ROOT/configs/selected_benchmark_tasks.json"

# ============================================
# PARSE ARGUMENTS
# ============================================
BENCHMARK_FILTER=""
USE_CASE_CATEGORY_FILTER=""
MODEL="${MODEL:-anthropic/claude-opus-4-6}"
CONCURRENCY=1        # harbor -n: trials per task
PARALLEL_TASKS=1     # number of simultaneous task processes
TIMEOUT_MULTIPLIER=10
RUN_BASELINE=true
RUN_FULL=true
CATEGORY="${CATEGORY:-staging}"
FULL_CONFIG="${FULL_CONFIG:-mcp-remote-direct}"
DRY_RUN=false
SKIP_COMPLETED=false
YES=false
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"

while [[ $# -gt 0 ]]; do
    case $1 in
        --benchmark)
            BENCHMARK_FILTER="$2"
            shift 2
            ;;
        --selection-file)
            SELECTION_FILE="$2"
            shift 2
            ;;
        --use-case-category)
            USE_CASE_CATEGORY_FILTER="$2"
            shift 2
            ;;
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
        --concurrency)
            CONCURRENCY="$2"
            shift 2
            ;;
        --parallel)
            PARALLEL_TASKS="$2"
            shift 2
            ;;
        --category)
            CATEGORY="$2"
            shift 2
            ;;
        --full-config)
            FULL_CONFIG="$2"
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
        --yes)
            YES=true
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

load_credentials

enforce_subscription_mode

if [ "$RUN_FULL" = true ] && [ -z "$SOURCEGRAPH_ACCESS_TOKEN" ]; then
    echo "WARNING: MCP mode requested but SOURCEGRAPH_ACCESS_TOKEN not set"
    echo "Skipping MCP runs."
    RUN_FULL=false
fi

ensure_fresh_token

# Derive baseline config and mcp_type values from FULL_CONFIG
BASELINE_CONFIG=$(baseline_config_for "$FULL_CONFIG")
BL_MCP_TYPE=$(config_to_mcp_type "$BASELINE_CONFIG")
FULL_MCP_TYPE=$(config_to_mcp_type "$FULL_CONFIG")

# ============================================
# EXTRACT TASKS FROM SELECTION FILE
# ============================================
# Python helper to extract task info grouped by benchmark
# Supports both standard format (benchmark field) and MCP-unique format (mcp_suite field).
# task_dir in both formats is relative to benchmarks/ (no benchmarks/ prefix).
extract_tasks() {
    python3 -c "
import json, sys

selection = json.load(open('$SELECTION_FILE'))
benchmark_filter = '$BENCHMARK_FILTER'
use_case_category_filter = '$USE_CASE_CATEGORY_FILTER'

for task in selection['tasks']:
    # Support both standard (benchmark) and MCP-unique (mcp_suite) selection files
    bm = task.get('benchmark') or task.get('mcp_suite', '')
    if not bm:
        continue
    if benchmark_filter and bm != benchmark_filter:
        continue
    if use_case_category_filter and task.get('use_case_category', '') != use_case_category_filter:
        continue
    # task_dir is relative to benchmarks/ in both formats
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

N_CONFIGS=0
[ "$RUN_BASELINE" = true ] && N_CONFIGS=$(( N_CONFIGS + 1 ))
[ "$RUN_FULL" = true ] && N_CONFIGS=$(( N_CONFIGS + 1 ))
TOTAL_AGENT_RUNS=$(( TOTAL_TASKS * N_CONFIGS ))

echo "=============================================="
echo "CodeContextBench Selected Tasks Runner"
echo "=============================================="
echo "Source:        $SELECTION_FILE"
echo "Model:         $MODEL"
echo "Total tasks:   $TOTAL_TASKS ($TOTAL_AGENT_RUNS agent runs across $N_CONFIGS config(s))"
echo "Parallel:      $PARALLEL_TASKS simultaneous task slots"
echo "Trials/task:   $CONCURRENCY"
echo "Configs:       $BASELINE_CONFIG=$RUN_BASELINE $FULL_CONFIG=$RUN_FULL"
echo "Skip done:     $SKIP_COMPLETED"
[ -n "$USE_CASE_CATEGORY_FILTER" ] && echo "Category:      $USE_CASE_CATEGORY_FILTER"
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
# CONFIRMATION GATE
# ============================================
if [ "$YES" != true ]; then
    echo "----------------------------------------------"
    echo "Ready to launch $TOTAL_AGENT_RUNS agent runs ($PARALLEL_TASKS parallel)."
    echo ""
    read -r -p "Press Enter to proceed, Ctrl+C to abort... " _
    echo ""
fi

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
# PARALLEL JOB POOL
# ============================================
declare -a _PIDS=()

# Block until fewer than PARALLEL_TASKS jobs are running.
# Uses wait -n to reap zombies (kill -0 sees zombies as alive; without reaping,
# slots never free even after child processes complete).
_wait_for_slot() {
    while [ "${#_PIDS[@]}" -ge "${PARALLEL_TASKS}" ]; do
        # Reap any completed child (non-blocking: wait for exactly one child to finish)
        wait -n "${_PIDS[@]}" 2>/dev/null || true
        # Rebuild PID list, excluding any that are no longer alive
        local new_pids=() p
        for p in "${_PIDS[@]}"; do
            kill -0 "$p" 2>/dev/null && new_pids+=("$p")
        done
        _PIDS=("${new_pids[@]}")
    done
}

# Wait for all pending jobs to complete
_drain_pool() {
    local p
    for p in "${_PIDS[@]}"; do
        wait "$p" 2>/dev/null || true
    done
    _PIDS=()
}

# Launch one task in the background; respects PARALLEL_TASKS slot limit
# Args: bm mcp_mode mcp_type task_id task_path jobs_dir
_launch_task() {
    local bm="$1" mcp_mode="$2" mcp_type="$3" task_id="$4" task_path="$5" jobs_dir="$6"
    local abs_path="$REPO_ROOT/$task_path"

    if [ ! -d "$abs_path" ]; then
        echo "WARNING: Task directory not found: $abs_path"
        return
    fi

    _wait_for_slot

    (
        local _df="${abs_path}/environment/Dockerfile"
        local _df_artifact="${abs_path}/environment/Dockerfile.artifact_only"
        local _df_swapped=false
        if [[ "$mcp_mode" == *-artifact ]] && [ -f "$_df_artifact" ]; then
            # Only backup if .run_bak doesn't already exist (idempotent on re-run after kill)
            if [ ! -f "${_df}.run_bak" ]; then
                cp "$_df" "${_df}.run_bak"
            fi
            cp "$_df_artifact" "$_df"
            _df_swapped=true
        fi

        BASELINE_MCP_TYPE=$mcp_type harbor run \
            --path "$abs_path" \
            --agent-import-path "$AGENT_PATH" \
            --model "$MODEL" \
            --jobs-dir "$jobs_dir" \
            -n "$CONCURRENCY" \
            --timeout-multiplier "$TIMEOUT_MULTIPLIER" \
            2>&1 | tee -a "${jobs_dir}.log" \
            || echo "WARNING: Task failed: $task_id (continuing...)"

        if [ "$_df_swapped" = true ]; then
            mv "${_df}.run_bak" "$_df"
        fi
    ) &
    _PIDS+=("$!")
    echo "  [${mcp_mode}] Started $task_id (PID ${_PIDS[-1]}, ${#_PIDS[@]}/${PARALLEL_TASKS} slots used)"
    # Stagger launches by 2s to avoid Harbor timestamp-based job directory collisions
    sleep 2
}

# ============================================
# MAIN EXECUTION — submit all tasks across benchmarks into shared pool
# ============================================

# First pass: create all jobs_dirs and collect them for post-processing
declare -A BL_JOBS_DIRS   # bm -> jobs_dir for baseline
declare -A FULL_JOBS_DIRS # bm -> jobs_dir for full

for bm in $(echo "${!BENCHMARK_COUNTS[@]}" | tr ' ' '\n' | sort); do
    if [ "$RUN_BASELINE" = true ]; then
        local_dir="runs/${CATEGORY}/${bm}_${MODEL_SHORT}_${TIMESTAMP}/${BASELINE_CONFIG}"
        BL_JOBS_DIRS[$bm]="$local_dir"
        mkdir -p "$local_dir"
    fi
    if [ "$RUN_FULL" = true ]; then
        local_dir="runs/${CATEGORY}/${bm}_${MODEL_SHORT}_${TIMESTAMP}/${FULL_CONFIG}"
        FULL_JOBS_DIRS[$bm]="$local_dir"
        mkdir -p "$local_dir"
    fi
done

# Submit all tasks: baseline first across all benchmarks, then full
# This keeps config passes clean while maximizing cross-benchmark parallelism
for config_pass in baseline full; do
    if [ "$config_pass" = "baseline" ] && [ "$RUN_BASELINE" != true ]; then
        continue
    fi
    if [ "$config_pass" = "full" ] && [ "$RUN_FULL" != true ]; then
        continue
    fi

    [ "$config_pass" = "baseline" ] && mcp_mode="$BASELINE_CONFIG" && mcp_type="$BL_MCP_TYPE"
    [ "$config_pass" = "full" ]     && mcp_mode="$FULL_CONFIG"     && mcp_type="$FULL_MCP_TYPE"

    echo ""
    echo "=== Submitting $config_pass tasks (${mcp_mode}) ==="

    for bm in $(echo "${!BENCHMARK_COUNTS[@]}" | tr ' ' '\n' | sort); do
        [ "$config_pass" = "baseline" ] && jobs_dir="${BL_JOBS_DIRS[$bm]}"
        [ "$config_pass" = "full" ]     && jobs_dir="${FULL_JOBS_DIRS[$bm]}"

        task_ids=$(echo "${BENCHMARK_TASK_IDS[$bm]}" | grep -v '^$')
        task_dirs=$(echo "${BENCHMARK_TASK_DIRS[$bm]}" | grep -v '^$')

        while IFS= read -r task_id && IFS= read -r task_path <&3; do
            [ -z "$task_id" ] && continue
            if is_task_completed "$jobs_dir" "$task_id"; then
                echo "  [${mcp_mode}] SKIP (completed): $task_id"
                continue
            fi
            _launch_task "$bm" "$mcp_mode" "$mcp_type" "$task_id" "$task_path" "$jobs_dir"
        done <<< "$task_ids" 3<<< "$task_dirs"
    done

    # Wait for all tasks in this config pass to finish before starting the next
    echo ""
    echo "=== Waiting for $config_pass tasks to complete... ==="
    _drain_pool
    echo "=== $config_pass pass complete ==="
done

unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true

# ============================================
# POST-PROCESSING
# ============================================
echo ""
echo "=== Extracting metrics and validating outputs ==="

for bm in $(echo "${!BENCHMARK_COUNTS[@]}" | tr ' ' '\n' | sort); do
    if [ "$RUN_BASELINE" = true ] && [ -n "${BL_JOBS_DIRS[$bm]:-}" ]; then
        extract_all_metrics "${BL_JOBS_DIRS[$bm]}" "$bm" "$BASELINE_CONFIG"
        validate_and_report "${BL_JOBS_DIRS[$bm]}" "$BASELINE_CONFIG"
    fi
    if [ "$RUN_FULL" = true ] && [ -n "${FULL_JOBS_DIRS[$bm]:-}" ]; then
        extract_all_metrics "${FULL_JOBS_DIRS[$bm]}" "$bm" "$FULL_CONFIG"
        validate_and_report "${FULL_JOBS_DIRS[$bm]}" "$FULL_CONFIG"
    fi
done

print_validation_summary

# Post-batch Docker cleanup
cleanup_docker_resources

echo ""
echo "=============================================="
echo "All Benchmarks Complete!"
echo "=============================================="
echo "Results: runs/${CATEGORY}/"
echo ""
echo "Generate report:"
echo "  python3 scripts/generate_eval_report.py --selected-tasks configs/selected_benchmark_tasks.json"
