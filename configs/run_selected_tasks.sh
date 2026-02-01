#!/bin/bash
# Unified Benchmark Runner — Reads tasks from selected_benchmark_tasks.json
#
# Runs selected benchmark tasks across 3 MCP configurations:
#   1. Baseline (no MCP)
#   2. MCP-NoDeepSearch (Sourcegraph tools without Deep Search)
#   3. MCP-Full (Sourcegraph + Deep Search hybrid)
#
# This script replaces the per-benchmark *_3config.sh scripts by reading
# the canonical task selection from selected_benchmark_tasks.json.
#
# Usage:
#   ./configs/run_selected_tasks.sh [OPTIONS]
#
# Options:
#   --benchmark BENCHMARK  Run only this benchmark (e.g., swebench_pro, locobench_agent)
#   --baseline-only        Run only baseline (no MCP)
#   --no-deepsearch-only   Run only MCP-NoDeepSearch
#   --full-only            Run only MCP-Full
#   --model MODEL          Override model (default: claude-opus-4-5-20251101)
#   --concurrency N        Concurrent tasks (default: 2)
#   --category CATEGORY    Run category (default: official)
#   --dry-run              Print tasks without running
#
# Prerequisites:
#   - selected_benchmark_tasks.json in repo root
#   - ~/evals/.env.local with ANTHROPIC_API_KEY
#   - SOURCEGRAPH_ACCESS_TOKEN in .env.local (for MCP modes)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
cd "$REPO_ROOT"

export PYTHONPATH="$(pwd):$PYTHONPATH"

SELECTION_FILE="$REPO_ROOT/selected_benchmark_tasks.json"

# ============================================
# PARSE ARGUMENTS
# ============================================
BENCHMARK_FILTER=""
MODEL="${MODEL:-anthropic/claude-opus-4-5-20251101}"
CONCURRENCY=2
TIMEOUT_MULTIPLIER=10
RUN_BASELINE=true
RUN_NO_DEEPSEARCH=true
RUN_FULL=true
CATEGORY="${CATEGORY:-official}"
DRY_RUN=false
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"

while [[ $# -gt 0 ]]; do
    case $1 in
        --benchmark)
            BENCHMARK_FILTER="$2"
            shift 2
            ;;
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
        --concurrency)
            CONCURRENCY="$2"
            shift 2
            ;;
        --category)
            CATEGORY="$2"
            shift 2
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

if { [ "$RUN_NO_DEEPSEARCH" = true ] || [ "$RUN_FULL" = true ]; } && [ -z "$SOURCEGRAPH_ACCESS_TOKEN" ]; then
    echo "WARNING: MCP modes requested but SOURCEGRAPH_ACCESS_TOKEN not set"
    echo "Skipping MCP runs."
    RUN_NO_DEEPSEARCH=false
    RUN_FULL=false
fi

# ============================================
# EXTRACT TASKS FROM SELECTION FILE
# ============================================
# Python helper to extract task info grouped by benchmark
extract_tasks() {
    python3 -c "
import json, sys

selection = json.load(open('$SELECTION_FILE'))
benchmark_filter = '$BENCHMARK_FILTER'

# Benchmark -> task_dir base path mapping
BENCH_BASE = {
    'swebench_pro': 'benchmarks/swebench_pro/tasks',
    'locobench_agent': 'benchmarks/locobench_agent/tasks',
    'big_code_mcp': 'benchmarks/big_code_mcp',
    'tac_mcp_value': 'benchmarks/tac_mcp_value',
    'github_mined': 'benchmarks/github_mined',
    'kubernetes_docs': 'benchmarks/kubernetes_docs',
    'dependeval_benchmark': 'benchmarks/dependeval_benchmark',
    'sweperf': 'benchmarks/sweperf',
    'repoqa': 'benchmarks/repoqa',
    '10figure': 'benchmarks/10figure',
    'dibench': 'benchmarks/dibench',
}

for task in selection['tasks']:
    bm = task['benchmark']
    if benchmark_filter and bm != benchmark_filter:
        continue
    task_dir = 'benchmarks/' + task['task_dir']
    print(f'{bm}\t{task[\"task_id\"]}\t{task_dir}')
"
}

# Read tasks into arrays grouped by benchmark
declare -A BENCHMARK_TASKS
declare -A BENCHMARK_COUNTS

while IFS=$'\t' read -r bm task_id task_dir; do
    BENCHMARK_TASKS[$bm]+="${task_dir}"$'\n'
    BENCHMARK_COUNTS[$bm]=$(( ${BENCHMARK_COUNTS[$bm]:-0} + 1 ))
done < <(extract_tasks)

if [ ${#BENCHMARK_TASKS[@]} -eq 0 ]; then
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
echo "Configs:       baseline=$RUN_BASELINE no_deepsearch=$RUN_NO_DEEPSEARCH full=$RUN_FULL"
echo ""
echo "Tasks per benchmark:"
for bm in $(echo "${!BENCHMARK_COUNTS[@]}" | tr ' ' '\n' | sort); do
    printf "  %-25s %d\n" "$bm" "${BENCHMARK_COUNTS[$bm]}"
done
echo ""

if [ "$DRY_RUN" = true ]; then
    echo "[DRY RUN] Would run these tasks:"
    for bm in $(echo "${!BENCHMARK_TASKS[@]}" | tr ' ' '\n' | sort); do
        echo ""
        echo "=== $bm (${BENCHMARK_COUNTS[$bm]} tasks) ==="
        echo "${BENCHMARK_TASKS[$bm]}" | head -5
        count=${BENCHMARK_COUNTS[$bm]}
        if [ "$count" -gt 5 ]; then
            echo "  ... and $(( count - 5 )) more"
        fi
    done
    exit 0
fi

# ============================================
# RUN FUNCTION
# ============================================
run_benchmark() {
    local bm=$1
    local mcp_mode=$2
    local mcp_type=$3

    local jobs_dir="runs/${CATEGORY}/${bm}_${MODEL_SHORT}_${TIMESTAMP}/${mcp_mode}"
    mkdir -p "$jobs_dir"

    echo ""
    echo "[${mcp_mode}] Running ${BENCHMARK_COUNTS[$bm]} ${bm} tasks..."

    # Get task directories for this benchmark
    local task_dirs
    task_dirs=$(echo "${BENCHMARK_TASKS[$bm]}" | grep -v '^$')

    while IFS= read -r task_path; do
        [ -z "$task_path" ] && continue
        local abs_path="$REPO_ROOT/$task_path"

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
            || echo "WARNING: Task failed: $task_path (continuing...)"
    done <<< "$task_dirs"
}

# ============================================
# MAIN EXECUTION
# ============================================
for bm in $(echo "${!BENCHMARK_TASKS[@]}" | tr ' ' '\n' | sort); do
    if [ "$RUN_BASELINE" = true ]; then
        run_benchmark "$bm" "baseline" "none"
    fi
    if [ "$RUN_NO_DEEPSEARCH" = true ]; then
        run_benchmark "$bm" "sourcegraph_no_deepsearch" "sourcegraph_no_deepsearch"
    fi
    if [ "$RUN_FULL" = true ]; then
        run_benchmark "$bm" "sourcegraph_hybrid" "sourcegraph_hybrid"
    fi
done

echo ""
echo "=============================================="
echo "All Benchmarks Complete!"
echo "=============================================="
echo "Results: runs/${CATEGORY}/"
echo ""
echo "Generate report:"
echo "  python3 scripts/generate_eval_report.py --selected-tasks selected_benchmark_tasks.json"
