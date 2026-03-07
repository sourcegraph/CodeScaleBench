#!/bin/bash
# OpenHands Harness 2-Config Runner
#
# Runs selected tasks across 2 configurations:
#   1. baseline-local-direct (BASELINE_MCP_TYPE=none)
#   2. mcp-remote-direct (BASELINE_MCP_TYPE=sourcegraph_full)
#
# Usage:
#   ./configs/openhands_2config.sh [OPTIONS]
#
# Options:
#   --baseline-only        Run only baseline (no MCP)
#   --full-only            Run only MCP-Full (sourcegraph_full)
#   --sequential           Run baseline then MCP sequentially (default: paired/parallel)
#   --model MODEL          Override model (default: anthropic/claude-sonnet-4-6)
#   --agent-path PATH      Override Harbor agent import path
#   --parallel N           Max parallel task subshells (default: 1)
#   --category CATEGORY    Run category label for jobs dir (default: staging)
#   --benchmark BENCH      Optional benchmark filter (e.g. csb_sdlc_feature, csb_sdlc_fix)
#   --task TASK_ID         Run only this task (further filters after --benchmark)
#   --subset FILENAME      Use subset JSON (relative to configs/, e.g. openhands_subset.json)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# Agent code lives in-repo under agents/
export PYTHONPATH="$(pwd):${PYTHONPATH:-}"

# Shared helpers (validation/reporting and run helpers)
source "$SCRIPT_DIR/_common.sh"
load_credentials

# OpenHands needs ANTHROPIC_API_KEY in the environment for Harbor's model key resolver.
# When using OAuth subscription (no explicit API key), extract the access token.
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ "$USE_SUBSCRIPTION" = "true" ]; then
    _oauth_token=$(python3 -c "
import json, os
creds_file = os.path.expanduser('~/.claude/.credentials.json')
if os.path.exists(creds_file):
    creds = json.load(open(creds_file))
    token = creds.get('claudeAiOauth', {}).get('accessToken', '')
    if token:
        print(token)
" 2>/dev/null)
    if [ -n "$_oauth_token" ]; then
        export ANTHROPIC_API_KEY="$_oauth_token"
        echo "Injected OAuth access token as ANTHROPIC_API_KEY for OpenHands"
    else
        echo "WARNING: Could not extract OAuth token from ~/.claude/.credentials.json"
        echo "  OpenHands will fail unless ANTHROPIC_API_KEY is set"
    fi
    unset _oauth_token
fi

SELECTION_FILE="$SCRIPT_DIR/selected_benchmark_tasks.json"
AGENT_PATH="${AGENT_PATH:-agents.harnesses.openhands:OpenHandsHarnessAgent}"
MODEL="${MODEL:-anthropic/claude-sonnet-4-6}"
CATEGORY="${CATEGORY:-staging}"
BENCHMARK_FILTER=""
TASK_FILTER=""
CONCURRENCY=2
TIMEOUT_MULTIPLIER=10
RUN_BASELINE=true
RUN_FULL=true
PAIRED_MODE=true  # Run baseline+MCP in parallel by default

while [[ $# -gt 0 ]]; do
    case $1 in
        --baseline-only)
            RUN_FULL=false
            PAIRED_MODE=false
            shift
            ;;
        --full-only)
            RUN_BASELINE=false
            PAIRED_MODE=false
            shift
            ;;
        --sequential)
            PAIRED_MODE=false
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
        --task)
            TASK_FILTER="$2"
            shift 2
            ;;
        --subset)
            SELECTION_FILE="$SCRIPT_DIR/$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

if [ ! -f "$SELECTION_FILE" ]; then
    echo "ERROR: Task selection file not found at $SELECTION_FILE"
    exit 1
fi

readarray -t TASK_ROWS < <(python3 - "$SELECTION_FILE" "$BENCHMARK_FILTER" "$TASK_FILTER" <<'PYEOF'
import json
import sys

selection_file = sys.argv[1]
benchmark_filter = sys.argv[2]
task_filter = sys.argv[3] if len(sys.argv) > 3 else ""

data = json.load(open(selection_file))
for task in data.get("tasks", []):
    if task.get("excluded", False):
        continue
    if benchmark_filter and task.get("benchmark") != benchmark_filter:
        continue
    if task_filter and task.get("task_id") != task_filter:
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
    PARALLEL_JOBS=0  # sentinel; setup_multi_accounts will auto-set
fi

# Multi-account support: rotate OAuth tokens across accounts.
REAL_HOME="$HOME"
setup_multi_accounts

_model_lower=$(echo "$MODEL" | awk -F/ '{print $NF}' | tr '[:upper:]' '[:lower:]')
case "$_model_lower" in
    *gpt-5.3-codex*|*gpt53codex*) MODEL_SHORT="gpt53codex" ;;
    *gpt-5*|*gpt5*) MODEL_SHORT="gpt5" ;;
    *gpt-4o*|*gpt4o*) MODEL_SHORT="gpt4o" ;;
    *gpt-4*|*gpt4*) MODEL_SHORT="gpt4" ;;
    *sonnet-4-6*|*sonnet46*) MODEL_SHORT="sonnet46" ;;
    *sonnet-4-5*|*sonnet45*) MODEL_SHORT="sonnet45" ;;
    *opus-4-6*|*opus46*) MODEL_SHORT="opus46" ;;
    *haiku-4-5*|*haiku45*) MODEL_SHORT="haiku45" ;;
    *) MODEL_SHORT=$(echo "$_model_lower" | tr -d '-' | tr -d '_' | cut -c1-12) ;;
esac

# Dotted model version for official directory structure (e.g. sonnet-4.6)
case "$_model_lower" in
    *sonnet-4-6*|*sonnet46*) MODEL_DIR="sonnet-4.6" ;;
    *sonnet-4-5*|*sonnet45*) MODEL_DIR="sonnet-4.5" ;;
    *opus-4-6*|*opus46*)     MODEL_DIR="opus-4.6" ;;
    *haiku-4-5*|*haiku45*)   MODEL_DIR="haiku-4.5" ;;
    *gpt-5*|*gpt5*)          MODEL_DIR="gpt-5" ;;
    *gpt-4o*|*gpt4o*)        MODEL_DIR="gpt-4o" ;;
    *)                        MODEL_DIR="$MODEL_SHORT" ;;
esac

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
JOBS_BASE="runs/${CATEGORY}/openhands_${MODEL_SHORT}_${TIMESTAMP}"
mkdir -p "$JOBS_BASE"

echo "=============================================="
echo "OpenHands 2-Config Runner"
echo "=============================================="
echo "Model: $MODEL"
echo "Agent path: $AGENT_PATH"
echo "Selection: $SELECTION_FILE"
echo "Benchmark filter: ${BENCHMARK_FILTER:-<all selected benchmarks>}"
echo "Task count: ${#TASK_IDS[@]}"
echo "Parallel jobs: $PARALLEL_JOBS"
echo "Jobs directory: $JOBS_BASE"
echo "Environment: ${HARBOR_ENV:-local-docker}"
echo "Run baseline: $RUN_BASELINE"
echo "Run MCP-Full: $RUN_FULL"
echo "Paired mode: $PAIRED_MODE"
echo "ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:+set (${#ANTHROPIC_API_KEY} chars)}"
echo "Storage override: ${DAYTONA_OVERRIDE_STORAGE:-<none>} MB"
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
    for task_id in "${TASK_IDS[@]}"; do
        _cost_guard_cmd+=(--task-id "$task_id")
    done
    [ "$RUN_BASELINE" = true ] && _cost_guard_cmd+=(--config "baseline-local-direct")
    [ "$RUN_FULL" = true ] && _cost_guard_cmd+=(--config "mcp-remote-direct")
    "${_cost_guard_cmd[@]}" || exit 1
    mark_daytona_cost_guard_ready
fi

_openhands_run_single() {
    local task_id=$1
    local _task_home=$2
    local config=${3:-baseline-local-direct}
    local mcp_type=${4:-none}
    local jobs_base=${5:-$JOBS_BASE}
    local task_path="${TASK_PATH_BY_ID[$task_id]}"

    # Map harness config name to official config dir name
    local official_config
    case "$config" in
        baseline-local-direct) official_config="baseline" ;;
        mcp-remote-direct)     official_config="sourcegraph_full" ;;
        *)                     official_config="$config" ;;
    esac

    # Build official-structure jobs dir:
    #   {jobs_base}/openhands/{csb_sdlc|csb_org}/{model_dir}/{suite}/{official_config}
    local suite="${TASK_SUITE_BY_ID[$task_id]}"
    local top_level
    if [[ "$suite" == csb_sdlc_* ]]; then
        top_level="csb_sdlc"
    else
        top_level="csb_org"
    fi
    local jobs_subdir="${jobs_base}/openhands/${top_level}/${MODEL_DIR}/${suite}/${official_config}"

    # Extract ANTHROPIC_API_KEY from this account's OAuth credentials.
    # run_tasks_parallel sets HOME=$_task_home for account rotation.
    if [ "$USE_SUBSCRIPTION" = "true" ]; then
        local _acct_token
        _acct_token=$(python3 -c "
import json, os
creds_file = os.path.join('${_task_home}', '.claude', '.credentials.json')
if os.path.exists(creds_file):
    creds = json.load(open(creds_file))
    token = creds.get('claudeAiOauth', {}).get('accessToken', '')
    if token: print(token)
" 2>/dev/null)
        if [ -n "$_acct_token" ]; then
            export ANTHROPIC_API_KEY="$_acct_token"
        fi
    fi

    case "$mcp_type" in
        none|sourcegraph_full)
            ;;
        *)
            echo "ERROR: unsupported MCP mode for openhands rollout: $mcp_type"
            return 1
            ;;
    esac

    mkdir -p "$jobs_subdir"

    if [ ! -d "$task_path" ]; then
        echo "ERROR: Task directory not found: $task_path"
        return 1
    fi

    # For MCP configs, swap in Dockerfile.sg_only (truncated source, agent uses MCP)
    local _run_path="$task_path"
    if [ "$mcp_type" = "sourcegraph_full" ]; then
        local _df_sgonly="${task_path}/environment/Dockerfile.sg_only"
        if [ -f "$_df_sgonly" ]; then
            local _mcp_temp_dir
            _mcp_temp_dir=$(mktemp -d "/tmp/mcp_${task_id}_XXXXXX")
            cp -a "${task_path}/." "${_mcp_temp_dir}/"
            cp "${_mcp_temp_dir}/environment/Dockerfile.sg_only" "${_mcp_temp_dir}/environment/Dockerfile"
            _run_path="$_mcp_temp_dir"
            echo "  [sg_only] Using truncated Dockerfile for MCP config: $task_id"
        else
            echo "  WARNING: No Dockerfile.sg_only for $task_id — MCP will have local source access"
        fi
    fi

    echo "Running task: $task_id ($config)"
    DAYTONA_LABEL_RUN_ID="$(basename "$JOBS_BASE")" \
    DAYTONA_LABEL_BENCHMARK="${TASK_SUITE_BY_ID[$task_id]}" \
    DAYTONA_LABEL_TASK_ID="$task_id" \
    DAYTONA_LABEL_CONFIG="$config" \
    DAYTONA_LABEL_CATEGORY="$CATEGORY" \
    TASK_SOURCE_DIR="$task_path" \
    BASELINE_MCP_TYPE="$mcp_type" harbor_run_guarded \
        --path "$_run_path" \
        --agent-import-path "$AGENT_PATH" \
        --model "$MODEL" \
        --jobs-dir "$jobs_subdir" \
        -n "$CONCURRENCY" \
        --timeout-multiplier "$TIMEOUT_MULTIPLIER" \
        ${DAYTONA_OVERRIDE_STORAGE:+--override-storage-mb "$DAYTONA_OVERRIDE_STORAGE"} \
        2>&1 | tee "${jobs_subdir}/${task_id}.log" \
        || echo "WARNING: Task $task_id ($config) failed"
}

run_mode() {
    local mode=$1
    local mcp_type=$2

    _mode_dispatch() {
        _openhands_run_single "$1" "$2" "$mode" "$mcp_type" "$JOBS_BASE"
    }

    run_tasks_parallel TASK_IDS _mode_dispatch || true
    validate_and_report "$JOBS_BASE" "$mode"
}

if [ "$PAIRED_MODE" = true ] && [ "$RUN_BASELINE" = true ] && [ "$RUN_FULL" = true ]; then
    # Run baseline + MCP simultaneously per task (interleaved, not sequential)
    export FULL_CONFIG="mcp-remote-direct"
    run_paired_configs TASK_IDS _openhands_run_single "$JOBS_BASE"
    validate_and_report "$JOBS_BASE" "baseline"
    validate_and_report "$JOBS_BASE" "sourcegraph_full"
else
    # Sequential mode (--baseline-only, --full-only, or --sequential)
    if [ "$RUN_BASELINE" = true ]; then
        run_mode "baseline-local-direct" "none"
    fi
    if [ "$RUN_FULL" = true ]; then
        run_mode "mcp-remote-direct" "sourcegraph_full"
    fi
fi

print_validation_summary "$JOBS_BASE"

echo ""
echo "Done. Results: $JOBS_BASE"
