#!/bin/bash
# Copilot Harness 2-Config Runner
#
# Runs selected tasks across 2 configurations:
#   1. baseline-local-direct (BASELINE_MCP_TYPE=none)
#   2. mcp-remote-direct (BASELINE_MCP_TYPE=sourcegraph_full)
#
# Usage:
#   ./configs/copilot_2config.sh [OPTIONS]
#
# Options:
#   --baseline-only        Run only baseline (no MCP)
#   --full-only            Run only MCP-Full (sourcegraph_full)
#   --model MODEL          Override model (default: anthropic/claude-opus-4-6)
#   --agent-path PATH      Override Harbor agent import path
#   --parallel N           Max parallel task subshells (default: 1)
#   --category CATEGORY    Run category label for jobs dir (default: staging)
#   --benchmark BENCH      Optional benchmark filter (e.g. csb_sdlc_feature, csb_sdlc_fix)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# Agent code lives in-repo under agents/
export PYTHONPATH="$(pwd):${PYTHONPATH:-}"

# Shared helpers (validation/reporting and run helpers)
source "$SCRIPT_DIR/_common.sh"

SELECTION_FILE="$SCRIPT_DIR/selected_benchmark_tasks.json"
AGENT_PATH="${AGENT_PATH:-agents.harnesses.copilot:CopilotHarnessAgent}"
MODEL="${MODEL:-anthropic/claude-opus-4-6}"
CATEGORY="${CATEGORY:-staging}"
BENCHMARK_FILTER=""
CONCURRENCY=2
TIMEOUT_MULTIPLIER=10
RUN_BASELINE=true
RUN_FULL=true

while [[ $# -gt 0 ]]; do
    case $1 in
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
        --agent-path)
            AGENT_PATH="$2"
            shift 2
            ;;
        --parallel)
            PARALLEL_JOBS="$2"
            shift 2
            ;;
        --category)
            CATEGORY="$2"
            shift 2
            ;;
        --benchmark)
            BENCHMARK_FILTER="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

if [ ! -f "$SELECTION_FILE" ]; then
    echo "ERROR: selected_benchmark_tasks.json not found at $SELECTION_FILE"
    exit 1
fi

readarray -t TASK_ROWS < <(python3 - "$SELECTION_FILE" "$BENCHMARK_FILTER" <<'PYEOF'
import json
import sys

selection_file = sys.argv[1]
benchmark_filter = sys.argv[2]

data = json.load(open(selection_file))
for task in data.get("tasks", []):
    if task.get("excluded", False):
        continue
    if benchmark_filter and task.get("benchmark") != benchmark_filter:
        continue
    task_id = task["task_id"]
    task_dir = task["task_dir"]
    benchmark = task.get("benchmark", "")
    print(f"{task_id}\tbenchmarks/{task_dir}\t{benchmark}")
PYEOF
)

if [ ${#TASK_ROWS[@]} -eq 0 ]; then
    echo "ERROR: no tasks selected after filters"
    exit 1
fi

declare -A TASK_PATH_BY_ID
declare -A TASK_SUITE_BY_ID
TASK_IDS=()
for row in "${TASK_ROWS[@]}"; do
    task_id=$(echo "$row" | cut -f1)
    task_path=$(echo "$row" | cut -f2)
    benchmark=$(echo "$row" | cut -f3)
    TASK_IDS+=("$task_id")
    TASK_PATH_BY_ID["$task_id"]="$task_path"
    TASK_SUITE_BY_ID["$task_id"]="$benchmark"
done

if [ -z "${PARALLEL_JOBS:-}" ] || [ "$PARALLEL_JOBS" -lt 1 ] 2>/dev/null; then
    PARALLEL_JOBS=1
fi

# run_tasks_parallel expects CLAUDE_HOMES; use current HOME for Copilot harness runs.
CLAUDE_HOMES=("$HOME")
REAL_HOME="$HOME"

_model_lower=$(echo "$MODEL" | awk -F/ '{print $NF}' | tr '[:upper:]' '[:lower:]')
case "$_model_lower" in
    *gpt-5.3-codex*|*gpt53codex*) MODEL_SHORT="gpt53codex" ;;
    *gpt-5*|*gpt5*) MODEL_SHORT="gpt5" ;;
    *gpt-4o*|*gpt4o*) MODEL_SHORT="gpt4o" ;;
    *gpt-4*|*gpt4*) MODEL_SHORT="gpt4" ;;
    *) MODEL_SHORT=$(echo "$_model_lower" | tr -d '-' | tr -d '_' | cut -c1-12) ;;
esac

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
JOBS_BASE="runs/${CATEGORY}/copilot_${MODEL_SHORT}_${TIMESTAMP}"
mkdir -p "$JOBS_BASE"

echo "=============================================="
echo "Copilot 2-Config Runner"
echo "=============================================="
echo "Model: $MODEL"
echo "Agent path: $AGENT_PATH"
echo "Benchmark filter: ${BENCHMARK_FILTER:-<all selected benchmarks>}"
echo "Task count: ${#TASK_IDS[@]}"
echo "Parallel jobs: $PARALLEL_JOBS"
echo "Jobs directory: $JOBS_BASE"
echo "Run baseline: $RUN_BASELINE"
echo "Run MCP-Full: $RUN_FULL"
echo ""

if [ "${HARBOR_ENV:-}" = "daytona" ]; then
    clear_daytona_cost_guard_ready
    _cost_guard_cmd=(
        python3 "$REPO_ROOT/scripts/daytona_cost_guard.py" preflight
        --selection-file "$SELECTION_FILE"
        --parallel-tasks "$PARALLEL_JOBS"
        --concurrency "$CONCURRENCY"
        --policy "$DAYTONA_COST_POLICY"
    )
    [ -n "$BENCHMARK_FILTER" ] && _cost_guard_cmd+=(--benchmark "$BENCHMARK_FILTER")
    [ "$RUN_BASELINE" = true ] && _cost_guard_cmd+=(--config "baseline-local-direct")
    [ "$RUN_FULL" = true ] && _cost_guard_cmd+=(--config "mcp-remote-direct")
    "${_cost_guard_cmd[@]}" || exit 1
    mark_daytona_cost_guard_ready
fi

_copilot_run_single() {
    local task_id=$1
    local _task_home=$2
    local config=${3:-baseline}
    local mcp_type=${4:-none}
    local jobs_base=${5:-$JOBS_BASE}
    local jobs_subdir="${jobs_base}/${config}"
    local task_path="${TASK_PATH_BY_ID[$task_id]}"

    case "$mcp_type" in
        none|sourcegraph_full)
            ;;
        *)
            echo "ERROR: unsupported MCP mode for copilot rollout: $mcp_type"
            return 1
            ;;
    esac

    mkdir -p "$jobs_subdir"

    if [ ! -d "$task_path" ]; then
        echo "ERROR: Task directory not found: $task_path"
        return 1
    fi

    echo "Running task: $task_id ($config)"
    DAYTONA_LABEL_RUN_ID="$(basename "$JOBS_BASE")" \
    DAYTONA_LABEL_BENCHMARK="${TASK_SUITE_BY_ID[$task_id]}" \
    DAYTONA_LABEL_TASK_ID="$task_id" \
    DAYTONA_LABEL_CONFIG="$config" \
    DAYTONA_LABEL_CATEGORY="$CATEGORY" \
    TASK_SOURCE_DIR="$task_path" \
    BASELINE_MCP_TYPE="$mcp_type" harbor_run_guarded \
        --path "$task_path" \
        --agent-import-path "$AGENT_PATH" \
        --model "$MODEL" \
        --jobs-dir "$jobs_subdir" \
        -n "$CONCURRENCY" \
        --timeout-multiplier "$TIMEOUT_MULTIPLIER" \
        2>&1 | tee "${jobs_subdir}/${task_id}.log" \
        || echo "WARNING: Task $task_id ($config) failed"
}

run_mode() {
    local mode=$1
    local mcp_type=$2

    jobs_subdir="${JOBS_BASE}/${mode}"
    mkdir -p "$jobs_subdir"

    _mode_dispatch() {
        _copilot_run_single "$1" "$2" "$mode" "$mcp_type" "$JOBS_BASE"
    }

    run_tasks_parallel TASK_IDS _mode_dispatch || true
    validate_and_report "$jobs_subdir" "$mode"
}

if [ "$RUN_BASELINE" = true ]; then
    run_mode "baseline-local-direct" "none"
fi

if [ "$RUN_FULL" = true ]; then
    run_mode "mcp-remote-direct" "sourcegraph_full"
fi

print_validation_summary "$JOBS_BASE"

echo ""
echo "Done. Results: $JOBS_BASE"
