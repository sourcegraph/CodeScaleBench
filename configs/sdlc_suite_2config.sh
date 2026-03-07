#!/bin/bash
# Generic SDLC 2-config runner (baseline + MCP).
# Suite-specific wrappers should set SDLC_SUITE, SDLC_SUITE_LABEL, and optionally FULL_CONFIG.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# Agent code lives in-repo under agents/
export PYTHONPATH="$(pwd):${PYTHONPATH:-}"

source "$SCRIPT_DIR/_common.sh"

# ============================================
# LOAD CREDENTIALS
# ============================================
load_credentials

enforce_subscription_mode
if [ -n "$SOURCEGRAPH_ACCESS_TOKEN" ]; then
    echo "SOURCEGRAPH_ACCESS_TOKEN: set (${#SOURCEGRAPH_ACCESS_TOKEN} chars)"
else
    echo "SOURCEGRAPH_ACCESS_TOKEN: not set"
fi
echo ""

ensure_fresh_token

# ============================================
# REQUIRED WRAPPER VARIABLES
# ============================================
SUITE="${SDLC_SUITE:-}"
SUITE_LABEL="${SDLC_SUITE_LABEL:-$SUITE}"
if [ -z "$SUITE" ]; then
    echo "ERROR: SDLC_SUITE is not set. Use a suite wrapper script in configs/."
    exit 1
fi
SUITE_STEM="${SUITE#csb_sdlc_}"

# ============================================
# CONFIGURATION
# ============================================
BENCHMARK_DIR="$(pwd)/benchmarks"
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
MODEL="${MODEL:-anthropic/claude-haiku-4-5-20251001}"
CONCURRENCY=1
TIMEOUT_MULTIPLIER="${TIMEOUT_MULTIPLIER:-10}"
RUN_BASELINE=true
RUN_FULL=true
CATEGORY="${CATEGORY:-staging}"
FULL_CONFIG="${FULL_CONFIG:-mcp-remote-direct}"
TASK_FILTERS=()

if [ ! -d "${BENCHMARK_DIR}/${SUITE}" ]; then
    echo "ERROR: Suite directory not found: ${BENCHMARK_DIR}/${SUITE}"
    exit 1
fi

mapfile -t ALL_TASK_IDS < <(find "${BENCHMARK_DIR}/${SUITE}" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)

# Re-sort tasks by expected duration descending (heaviest first).
# This ensures long-running tasks start immediately in the first parallel wave,
# overlapping with many lighter tasks instead of blocking the tail end.
mapfile -t ALL_TASK_IDS < <(python3 - "${BENCHMARK_DIR}/${SUITE}" "${ALL_TASK_IDS[@]}" <<'SORT_EOF'
import sys, os, re
suite_dir = sys.argv[1]
task_ids = sys.argv[2:]

def task_weight(task_id):
    toml_path = os.path.join(suite_dir, task_id, "task.toml")
    try:
        with open(toml_path) as f:
            text = f.read()
    except OSError:
        return 0
    build = 900  # default
    agent = 1200  # default
    m = re.search(r'build_timeout_sec\s*=\s*(\d+)', text)
    if m:
        build = int(m.group(1))
    m = re.search(r'timeout_sec\s*=\s*(\d+)', text)
    if m:
        agent = int(m.group(1))
    m = re.search(r'time_limit_sec\s*=\s*(\d+)', text)
    if m:
        agent = max(agent, int(m.group(1)))
    return build + agent

for tid in sorted(task_ids, key=task_weight, reverse=True):
    print(tid)
SORT_EOF
)

# Parse arguments
SKIP_PREBUILD=false
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
        --category)
            CATEGORY="$2"
            shift 2
            ;;
        --parallel)
            PARALLEL_JOBS="$2"
            shift 2
            ;;
        --task)
            TASK_FILTERS+=("$2")
            shift 2
            ;;
        --no-prebuild)
            SKIP_PREBUILD=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

if [ ${#TASK_FILTERS[@]} -gt 0 ]; then
    TASK_IDS=("${TASK_FILTERS[@]}")
else
    TASK_IDS=("${ALL_TASK_IDS[@]}")
fi

if [ ${#TASK_IDS[@]} -eq 0 ]; then
    echo "ERROR: No tasks found in ${BENCHMARK_DIR}/${SUITE}"
    exit 1
fi

setup_dual_accounts

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
JOBS_BASE="runs/${CATEGORY}/${SUITE_STEM}_${MODEL_SHORT}_${TIMESTAMP}"
BL_CONFIG=$(baseline_config_for "$FULL_CONFIG")
BL_MCP=$(config_to_mcp_type "$BL_CONFIG")
FULL_MCP=$(config_to_mcp_type "$FULL_CONFIG")

echo "=============================================="
echo "SDLC: ${SUITE_LABEL}"
echo "=============================================="
echo "Suite: ${SUITE}"
echo "Model: ${MODEL}"
echo "Task count: ${#TASK_IDS[@]}"
echo "Concurrency: ${CONCURRENCY}"
echo "Parallel jobs: ${PARALLEL_JOBS}"
echo "Jobs directory: ${JOBS_BASE}"
echo "Run baseline: ${RUN_BASELINE}"
echo "Run MCP-Full: ${RUN_FULL} (${FULL_CONFIG})"
echo ""

mkdir -p "${JOBS_BASE}"

if [ "${HARBOR_ENV:-}" = "daytona" ]; then
    clear_daytona_cost_guard_ready
    _cost_guard_cmd=(
        python3 "$REPO_ROOT/scripts/daytona_cost_guard.py" preflight
        --suite "$SUITE"
        --parallel-tasks "$PARALLEL_JOBS"
        --concurrency "$CONCURRENCY"
        --policy "$DAYTONA_COST_POLICY"
    )
    for task_id in "${TASK_IDS[@]}"; do
        _cost_guard_cmd+=(--task-id "$task_id")
    done
    [ "$RUN_BASELINE" = true ] && _cost_guard_cmd+=(--config "$BL_CONFIG")
    [ "$RUN_FULL" = true ] && _cost_guard_cmd+=(--config "$FULL_CONFIG")
    "${_cost_guard_cmd[@]}" || exit 1
    mark_daytona_cost_guard_ready
fi

log_section() {
    echo ""
    echo "========================================"
    echo "$1"
    echo "========================================"
    echo ""
}

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
                --selected-tasks "$SCRIPT_DIR/selected_benchmark_tasks.json" \
                2>&1 || echo "  WARNING: metrics extraction failed for $(basename "$result_dir")"
        fi
    done
}

_sdlc_run_single() {
    local task_id=$1
    local task_home=$2
    local config=${3:-baseline-local-direct}
    local mcp_type=${4:-none}
    local jobs_base=${5:-$JOBS_BASE}
    local jobs_subdir="${jobs_base}/${config}"
    local task_path="${BENCHMARK_DIR}/${SUITE}/${task_id}"
    local run_task_path="$task_path"
    local temp_task_dir=""

    mkdir -p "$jobs_subdir"

    if [ ! -d "$task_path" ]; then
        echo "ERROR: Task directory not found: $task_path"
        return 1
    fi

    if [ "$config" = "baseline-local-artifact" ] && \
       grep -q "No local repositories are pre-checked out." "${task_path}/instruction.md"; then
        echo "ERROR: baseline-local-artifact requires local repos, but ${task_id} declares none in instruction.md"
        return 1
    fi

    # Derive source access and verifier mode from config name.
    # config_to_mcp_type sets SOURCE_ACCESS and VERIFIER_MODE globals.
    config_to_mcp_type "$config" > /dev/null

    # Dockerfile selection based on SOURCE_ACCESS and VERIFIER_MODE:
    #   local  + direct   → original Dockerfile (no swap needed)
    #   local  + artifact → Dockerfile.artifact_baseline
    #   remote + direct   → Dockerfile.sg_only (empty workspace, verifier restores repo)
    #   remote + artifact → Dockerfile.artifact_only (repo backup + sentinel for answer.json verifier)
    if [ "$SOURCE_ACCESS" = "local" ] && [ "$VERIFIER_MODE" = "artifact" ]; then
        local artifact_baseline="${task_path}/environment/Dockerfile.artifact_baseline"
        if [ ! -f "$artifact_baseline" ]; then
            echo "ERROR: Missing Dockerfile.artifact_baseline for $task_id at $artifact_baseline"
            return 1
        fi
        temp_task_dir="/tmp/artifact_bl_${task_id}"
        rm -rf "$temp_task_dir"
        mkdir -p "$temp_task_dir"
        cp -a "${task_path}/." "${temp_task_dir}/"
        cp "${temp_task_dir}/environment/Dockerfile.artifact_baseline" "${temp_task_dir}/environment/Dockerfile"
        run_task_path="$temp_task_dir"

    elif [ "$SOURCE_ACCESS" = "remote" ] && [ "$VERIFIER_MODE" = "direct" ]; then
        local sgonly="${task_path}/environment/Dockerfile.sg_only"
        if [ ! -f "$sgonly" ]; then
            echo "ERROR: Missing Dockerfile.sg_only for $task_id at $sgonly"
            return 1
        fi
        temp_task_dir="/tmp/sgonly_${task_id}"
        rm -rf "$temp_task_dir"
        mkdir -p "$temp_task_dir"
        cp -a "${task_path}/." "${temp_task_dir}/"
        cp "${temp_task_dir}/environment/Dockerfile.sg_only" "${temp_task_dir}/environment/Dockerfile"
        run_task_path="$temp_task_dir"

    elif [ "$SOURCE_ACCESS" = "remote" ] && [ "$VERIFIER_MODE" = "artifact" ]; then
        # Prefer Dockerfile.artifact_only (has repo clone + /repo_full for verifier)
        # over Dockerfile.sg_only (empty workspace, no /repo_full).
        # Code-change verifiers need /repo_full to restore repo and apply diffs.
        local chosen_dockerfile=""
        if [ -f "${task_path}/environment/Dockerfile.artifact_only" ]; then
            chosen_dockerfile="Dockerfile.artifact_only"
        elif [ -f "${task_path}/environment/Dockerfile.sg_only" ]; then
            echo "WARNING: No Dockerfile.artifact_only for $task_id — falling back to Dockerfile.sg_only"
            chosen_dockerfile="Dockerfile.sg_only"
        else
            echo "ERROR: No Dockerfile.artifact_only or Dockerfile.sg_only for $task_id"
            return 1
        fi
        temp_task_dir="/tmp/artifact_${task_id}"
        rm -rf "$temp_task_dir"
        mkdir -p "$temp_task_dir"
        cp -a "${task_path}/." "${temp_task_dir}/"
        cp "${temp_task_dir}/environment/${chosen_dockerfile}" "${temp_task_dir}/environment/Dockerfile"
        run_task_path="$temp_task_dir"
    fi

    echo "Running task: $task_id ($config) [HOME=$task_home]"

    local job_name="${SUITE}_${task_id}_${config}"
    job_name="${job_name//[^[:alnum:]_.-]/-}"
    job_name=$(echo "$job_name" | tr '[:upper:]' '[:lower:]')

    local instruction_variant="default"
    if [[ "$config" == *mcp-scip* ]]; then
        instruction_variant="mcp_scip"
    elif [[ "$mcp_type" != "none" ]]; then
        instruction_variant="mcp"
    fi

    TASK_SOURCE_DIR="$task_path" \
    INSTRUCTION_VARIANT="$instruction_variant" \
    DAYTONA_LABEL_RUN_ID="$(basename "$JOBS_BASE")" \
    DAYTONA_LABEL_BENCHMARK="$SUITE" \
    DAYTONA_LABEL_TASK_ID="$task_id" \
    DAYTONA_LABEL_CONFIG="$config" \
    DAYTONA_LABEL_CATEGORY="$CATEGORY" \
    BASELINE_MCP_TYPE=$mcp_type harbor_run_guarded \
        --job-name "$job_name" \
        --path "$run_task_path" \
        --agent-import-path "$AGENT_PATH" \
        --model "$MODEL" \
        --jobs-dir "$jobs_subdir" \
        -n $CONCURRENCY \
        --timeout-multiplier $TIMEOUT_MULTIPLIER \
        ${DAYTONA_OVERRIDE_STORAGE:+--override-storage-mb "$DAYTONA_OVERRIDE_STORAGE"} \
        2>&1 | tee "${jobs_subdir}/${task_id}.log" \
        || {
            echo "WARNING: Task $task_id ($config) failed (exit code: $?)"
        }

    if [ -n "$temp_task_dir" ] && [ -d "$temp_task_dir" ]; then
        rm -rf "$temp_task_dir"
    fi
}

run_task_batch() {
    local mode=$1
    local mcp_type=$2

    ensure_fresh_token_all
    log_section "Running ${SUITE_STEM} - Mode: $mode"

    _seq_run() {
        _sdlc_run_single "$1" "$2" "$mode" "$mcp_type" "$JOBS_BASE"
    }
    run_canary_then_batch TASK_IDS _seq_run "${JOBS_BASE}/${mode}" "$mode"

    extract_all_metrics "${JOBS_BASE}/${mode}" "${SUITE}" "$mode"
    validate_and_report "${JOBS_BASE}/${mode}" "$mode"
    log_section "Completed ${SUITE_STEM} - Mode: $mode"
}

# Pre-build all Docker images to warm the cache before agent runs.
# This moves Docker build time out of the critical path (API session slots).
if [ "$SKIP_PREBUILD" = false ] && [ "${HARBOR_ENV:-}" = "daytona" ]; then
    log_section "Skipping local prebuild for ${SUITE} because Daytona builds remotely"
elif [ "$SKIP_PREBUILD" = false ]; then
    log_section "Pre-building Docker images for ${SUITE}"
    # Pass selected task IDs so prebuild only builds images for tasks we'll run
    _task_list=$(IFS=,; echo "${TASK_IDS[*]}")
    prebuild_images "$SUITE" --tasks "$_task_list"
fi

if [ "$RUN_BASELINE" = true ] && [ "$RUN_FULL" = true ]; then
    run_paired_configs TASK_IDS _sdlc_run_single "$JOBS_BASE"

    for config in "$BL_CONFIG" "$FULL_CONFIG"; do
        if [ -d "${JOBS_BASE}/${config}" ]; then
            extract_all_metrics "${JOBS_BASE}/${config}" "${SUITE}" "$config"
            validate_and_report "${JOBS_BASE}/${config}" "$config"
        fi
    done
elif [ "$RUN_BASELINE" = true ]; then
    run_task_batch "$BL_CONFIG" "$BL_MCP"
elif [ "$RUN_FULL" = true ]; then
    run_task_batch "$FULL_CONFIG" "$FULL_MCP"
fi

print_validation_summary "$JOBS_BASE"

# Post-batch Docker cleanup — reclaim dangling images, orphan volumes, BuildKit cache
cleanup_docker_resources

echo ""
echo "=============================================="
echo "SDLC: ${SUITE_LABEL} Complete!"
echo "=============================================="
echo "Results saved to: ${JOBS_BASE}"
echo ""
echo "View results:"
echo "  cat ${JOBS_BASE}/*/*/result.json | jq -r '.trials[].verifier_result.rewards.reward'"
