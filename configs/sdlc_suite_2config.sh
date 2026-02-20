#!/bin/bash
# Generic SDLC 2-config runner (baseline + sourcegraph_full).
# Suite-specific wrappers should set SDLC_SUITE and SDLC_SUITE_LABEL.

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
SUITE_STEM="${SUITE#ccb_}"

# ============================================
# CONFIGURATION
# ============================================
BENCHMARK_DIR="$(pwd)/benchmarks"
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
MODEL="${MODEL:-anthropic/claude-opus-4-6}"
CONCURRENCY=1
TIMEOUT_MULTIPLIER=10
RUN_BASELINE=true
RUN_FULL=true
CATEGORY="${CATEGORY:-staging}"
FULL_CONFIG="${FULL_CONFIG:-sourcegraph_full}"
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
    local config=${3:-baseline}
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

    # For MCP-full runs, enforce sg_only Docker build env without mutating the
    # original task path (baseline may run in parallel on the same task).
    if [ "$config" = "sourcegraph_full" ]; then
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

    elif [ "$config" = "artifact_full" ]; then
        local artifact="${task_path}/environment/Dockerfile.artifact_only"
        if [ ! -f "$artifact" ]; then
            echo "ERROR: Missing Dockerfile.artifact_only for $task_id at $artifact"
            return 1
        fi

        temp_task_dir="/tmp/artifact_${task_id}"
        rm -rf "$temp_task_dir"
        mkdir -p "$temp_task_dir"
        cp -a "${task_path}/." "${temp_task_dir}/"
        cp "${temp_task_dir}/environment/Dockerfile.artifact_only" "${temp_task_dir}/environment/Dockerfile"
        run_task_path="$temp_task_dir"
    fi

    echo "Running task: $task_id ($config) [HOME=$task_home]"

    local job_name="${SUITE}_${task_id}_${config}"
    job_name="${job_name//[^[:alnum:]_.-]/-}"
    job_name=$(echo "$job_name" | tr '[:upper:]' '[:lower:]')

    BASELINE_MCP_TYPE=$mcp_type harbor run \
        --job-name "$job_name" \
        --path "$run_task_path" \
        --agent-import-path "$AGENT_PATH" \
        --model "$MODEL" \
        --jobs-dir "$jobs_subdir" \
        -n $CONCURRENCY \
        --timeout-multiplier $TIMEOUT_MULTIPLIER \
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
if [ "$SKIP_PREBUILD" = false ]; then
    log_section "Pre-building Docker images for ${SUITE}"
    prebuild_images "$SUITE"
fi

if [ "$RUN_BASELINE" = true ] && [ "$RUN_FULL" = true ]; then
    run_paired_configs TASK_IDS _sdlc_run_single "$JOBS_BASE"

    for config in baseline "$FULL_CONFIG"; do
        if [ -d "${JOBS_BASE}/${config}" ]; then
            extract_all_metrics "${JOBS_BASE}/${config}" "${SUITE}" "$config"
            validate_and_report "${JOBS_BASE}/${config}" "$config"
        fi
    done
elif [ "$RUN_BASELINE" = true ]; then
    run_task_batch "baseline" "none"
elif [ "$RUN_FULL" = true ]; then
    run_task_batch "$FULL_CONFIG" "$FULL_CONFIG"
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
