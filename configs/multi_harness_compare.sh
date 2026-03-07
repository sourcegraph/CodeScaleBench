#!/bin/bash
# Multi-harness compare scaffold for Codex, Cursor, Gemini, Copilot, and OpenHands.
#
# Runs selected tasks across baseline and sourcegraph_full variants for each harness.
#
# Usage:
#   ./configs/multi_harness_compare.sh [OPTIONS]
#
# Options:
#   --harnesses LIST       Comma-separated subset (default: codex,cursor,gemini,copilot,openhands)
#   --benchmark BENCH      Optional benchmark filter (e.g. csb_org_crossrepo)
#   --task-ids LIST        Optional comma-separated task IDs from selected tasks
#   --selection-file PATH  Selected tasks JSON (default: configs/selected_benchmark_tasks.json)
#   --registry PATH        Harness registry JSON (default: configs/harness_registry.json)
#   --category CATEGORY    Run category label for jobs dir (default: staging)
#   --parallel N           Max task subshells per variant (default: 1)
#   --concurrency N        Harbor -n concurrency per task (default: 1)
#   --dry-run              Print planned runs without executing Harbor

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
cd "$REPO_ROOT"

# Agent code lives in-repo under agents/
export PYTHONPATH="$(pwd):${PYTHONPATH:-}"

source "$SCRIPT_DIR/_common.sh"
load_credentials
enforce_subscription_mode

SELECTION_FILE="$REPO_ROOT/configs/selected_benchmark_tasks.json"
REGISTRY_FILE="$REPO_ROOT/configs/harness_registry.json"
CATEGORY="${CATEGORY:-staging}"
BENCHMARK_FILTER=""
TASK_ID_FILTER=""
HARNESS_LIST="codex,cursor,gemini,copilot,openhands"
PARALLEL_JOBS=1
CONCURRENCY=1
TIMEOUT_MULTIPLIER=10
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --harnesses)
            HARNESS_LIST="$2"
            shift 2
            ;;
        --benchmark)
            BENCHMARK_FILTER="$2"
            shift 2
            ;;
        --task-ids)
            TASK_ID_FILTER="$2"
            shift 2
            ;;
        --selection-file)
            SELECTION_FILE="$2"
            shift 2
            ;;
        --registry)
            REGISTRY_FILE="$2"
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
        --concurrency)
            CONCURRENCY="$2"
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

if [ ! -f "$SELECTION_FILE" ]; then
    echo "ERROR: selection file not found: $SELECTION_FILE"
    exit 1
fi
if [ ! -f "$REGISTRY_FILE" ]; then
    echo "ERROR: harness registry not found: $REGISTRY_FILE"
    exit 1
fi

if [ -z "${PARALLEL_JOBS:-}" ] || [ "$PARALLEL_JOBS" -lt 1 ] 2>/dev/null; then
    PARALLEL_JOBS=1
fi
if [ -z "${CONCURRENCY:-}" ] || [ "$CONCURRENCY" -lt 1 ] 2>/dev/null; then
    CONCURRENCY=1
fi

IFS=',' read -r -a HARNESS_IDS <<< "$HARNESS_LIST"
if [ "${#HARNESS_IDS[@]}" -eq 0 ]; then
    echo "ERROR: no harnesses selected"
    exit 1
fi

declare -A HARNESS_AGENT_PATH
declare -A HARNESS_MODEL
readarray -t REGISTRY_ROWS < <(python3 - "$REGISTRY_FILE" <<'PYEOF'
import json
import sys

registry = json.load(open(sys.argv[1]))
required = {"codex", "cursor", "gemini", "copilot", "openhands"}
missing = required - set(registry.keys())
if missing:
    raise SystemExit(f"missing harness entries: {sorted(missing)}")

for harness_id, cfg in registry.items():
    ap = cfg.get("agent_import_path")
    model = cfg.get("default_model")
    modes = cfg.get("allowed_mcp_modes", [])
    if ap is None or model is None:
        raise SystemExit(f"missing fields for {harness_id}")
    if sorted(modes) != ["none", "sourcegraph_full"]:
        raise SystemExit(f"unsupported MCP modes for {harness_id}: {modes}")
    print(f"{harness_id}\t{ap}\t{model}")
PYEOF
)

for row in "${REGISTRY_ROWS[@]}"; do
    harness_id=$(echo "$row" | cut -f1)
    HARNESS_AGENT_PATH["$harness_id"]=$(echo "$row" | cut -f2)
    HARNESS_MODEL["$harness_id"]=$(echo "$row" | cut -f3)
done

for harness_id in "${HARNESS_IDS[@]}"; do
    if [ -z "${HARNESS_AGENT_PATH[$harness_id]:-}" ] || [ -z "${HARNESS_MODEL[$harness_id]:-}" ]; then
        echo "ERROR: harness '$harness_id' not found in registry $REGISTRY_FILE"
        exit 1
    fi
done

readarray -t TASK_ROWS < <(python3 - "$SELECTION_FILE" "$BENCHMARK_FILTER" "$TASK_ID_FILTER" <<'PYEOF'
import json
import sys

selection_file = sys.argv[1]
benchmark_filter = sys.argv[2]
task_ids_filter = {t for t in sys.argv[3].split(",") if t}

data = json.load(open(selection_file))
for task in data.get("tasks", []):
    if task.get("excluded", False):
        continue
    if benchmark_filter and task.get("benchmark") != benchmark_filter:
        continue
    task_id = task["task_id"]
    if task_ids_filter and task_id not in task_ids_filter:
        continue
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

HARNESS_LABEL="$(IFS=- ; echo "${HARNESS_IDS[*]}")"
CONFIG_LABEL="baseline-sourcegraph_full"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
JOBS_BASE="runs/${CATEGORY}/multi_harness_${HARNESS_LABEL}_${CONFIG_LABEL}_${TIMESTAMP}"
mkdir -p "$JOBS_BASE"

# run_tasks_parallel expects CLAUDE_HOMES.
CLAUDE_HOMES=("$HOME")
REAL_HOME="$HOME"

echo "=============================================="
echo "Multi-Harness Compare Scaffold"
echo "=============================================="
echo "Harnesses: $HARNESS_LIST"
echo "Benchmark filter: ${BENCHMARK_FILTER:-<all selected benchmarks>}"
echo "Task ID filter: ${TASK_ID_FILTER:-<none>}"
echo "Task count: ${#TASK_IDS[@]}"
echo "Parallel jobs: $PARALLEL_JOBS"
echo "Harbor concurrency: $CONCURRENCY"
echo "Dry run: $DRY_RUN"
echo "Jobs directory base: $JOBS_BASE"
echo ""

if [ "$DRY_RUN" = false ] && [ "${HARBOR_ENV:-}" = "daytona" ]; then
    clear_daytona_cost_guard_ready
    _cost_guard_cmd=(
        python3 "$REPO_ROOT/scripts/daytona_cost_guard.py" preflight
        --selection-file "$SELECTION_FILE"
        --parallel-tasks "$PARALLEL_JOBS"
        --concurrency "$CONCURRENCY"
        --policy "$DAYTONA_COST_POLICY"
    )
    [ -n "$BENCHMARK_FILTER" ] && _cost_guard_cmd+=(--benchmark "$BENCHMARK_FILTER")
    for task_id in "${TASK_IDS[@]}"; do
        _cost_guard_cmd+=(--task-id "$task_id")
    done
    for harness_id in "${HARNESS_IDS[@]}"; do
        _cost_guard_cmd+=(--config "baseline-local-direct" --config "mcp-remote-direct")
    done
    "${_cost_guard_cmd[@]}" || exit 1
    mark_daytona_cost_guard_ready
fi

run_variant() {
    local harness_id=$1
    local mode=$2
    local mcp_type=$3
    local agent_path="${HARNESS_AGENT_PATH[$harness_id]}"
    local model="${HARNESS_MODEL[$harness_id]}"
    local jobs_dir="${JOBS_BASE}/${harness_id}_${mode}"

    mkdir -p "$jobs_dir"
    echo "Variant: ${harness_id}_${mode} (mcp=${mcp_type}, model=${model})"

    _variant_run_single() {
        local task_id=$1
        local _task_home=$2
        local task_path="${TASK_PATH_BY_ID[$task_id]}"

        if [ ! -d "$task_path" ]; then
            echo "WARNING: task directory not found: $task_path"
            return 1
        fi

        if [ "$DRY_RUN" = true ]; then
            echo "[DRY RUN] BASELINE_MCP_TYPE=$mcp_type harbor_run_guarded --path $task_path --agent-import-path $agent_path --model $model --jobs-dir $jobs_dir -n $CONCURRENCY --timeout-multiplier $TIMEOUT_MULTIPLIER"
            return 0
        fi

        DAYTONA_LABEL_RUN_ID="$(basename "$JOBS_BASE")" \
        DAYTONA_LABEL_BENCHMARK="${TASK_SUITE_BY_ID[$task_id]}" \
        DAYTONA_LABEL_TASK_ID="$task_id" \
        DAYTONA_LABEL_CONFIG="${harness_id}_${mode}" \
        DAYTONA_LABEL_CATEGORY="$CATEGORY" \
        TASK_SOURCE_DIR="$task_path" \
        BASELINE_MCP_TYPE="$mcp_type" harbor_run_guarded \
            --path "$task_path" \
            --agent-import-path "$agent_path" \
            --model "$model" \
            --jobs-dir "$jobs_dir" \
            -n "$CONCURRENCY" \
            --timeout-multiplier "$TIMEOUT_MULTIPLIER" \
            2>&1 | tee -a "${jobs_dir}.log" \
            || echo "WARNING: failed ${harness_id}_${mode} $task_id"
    }

    run_tasks_parallel TASK_IDS _variant_run_single || true
}

for harness_id in "${HARNESS_IDS[@]}"; do
    run_variant "$harness_id" "baseline" "none"
    run_variant "$harness_id" "sourcegraph_full" "sourcegraph_full"
done

echo ""
echo "Completed. Results directory: $JOBS_BASE"
