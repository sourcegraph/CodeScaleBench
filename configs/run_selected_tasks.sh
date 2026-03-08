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
#   --benchmark BENCHMARK           Run only this benchmark (e.g., csb_sdlc_feature, csb_sdlc_fix)
#   --selection-file PATH           Use alternate selection file (default: selected_benchmark_tasks.json)
#   --use-case-category CATEGORY    Filter by MCP-unique use case category (A-J), only valid with --selection-file
#   --baseline-only                 Run only baseline (no MCP)
#   --full-only                     Run only MCP-Full (mcp-remote-direct)
#   --full-config CONFIG            Full config name (default: mcp-remote-direct)
#                                   Use mcp-remote-artifact for artifact-based evaluation
#   --model MODEL                   Override model (default: claude-haiku-4-5-20251001)
#   --concurrency N                 Trials per task via harbor -n (default: 1)
#   --parallel N                    Parallel task slots (default: 1). Set to 8 for multi-account runs.
#   --category CATEGORY             Run category (default: staging)
#   --skip-completed                Skip tasks that already have result.json + task_metrics.json
#   --dry-run                       Print tasks without running
#   --skip-prebuild                 Skip Docker image pre-build (use when images already cached)
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
DAYTONA_COST_POLICY="${DAYTONA_COST_POLICY:-$REPO_ROOT/configs/daytona_cost_policy.json}"
DAYTONA_PARALLEL_TASK_CAP="${DAYTONA_PARALLEL_TASK_CAP:-60}"

# ============================================
# PARSE ARGUMENTS
# ============================================
BENCHMARK_FILTER=""
USE_CASE_CATEGORY_FILTER=""
MODEL="${MODEL:-anthropic/claude-haiku-4-5-20251001}"
CONCURRENCY=1        # harbor -n: trials per task
PARALLEL_TASKS=0     # 0 = auto-detect from accounts; overridden by --parallel N
TIMEOUT_MULTIPLIER="${TIMEOUT_MULTIPLIER:-10}"
RUN_BASELINE=true
RUN_FULL=true
CATEGORY="${CATEGORY:-staging}"
FULL_CONFIG="${FULL_CONFIG:-mcp-remote-direct}"
_FULL_CONFIG_EXPLICIT=false
DRY_RUN=false
SKIP_COMPLETED=false
SKIP_PREBUILD=false
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
            _FULL_CONFIG_EXPLICIT=true
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
        --skip-prebuild)
            SKIP_PREBUILD=true
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

# Auto-detect artifact config for MCP-unique selection files
# MCP-unique tasks use mcp_suite (not benchmark) and default to artifact configs.
# Only triggers when ALL filtered tasks are MCP-unique AND all are artifact-only
# (no task has "direct" in its verification_modes).
if [ "$_FULL_CONFIG_EXPLICIT" = false ]; then
    if python3 -c "
import json, sys
data = json.load(open('$SELECTION_FILE'))
bm_filter = '$BENCHMARK_FILTER'
cat_filter = '$USE_CASE_CATEGORY_FILTER'
tasks = data.get('tasks', [])
# Apply same filters as extract_tasks()
filtered = []
for t in tasks:
    suite = t.get('benchmark') or t.get('mcp_suite', '')
    if not suite:
        continue
    if bm_filter and suite != bm_filter:
        continue
    if cat_filter and t.get('use_case_category', '') != cat_filter:
        continue
    filtered.append(t)
if not filtered:
    sys.exit(1)
all_mcp = all('mcp_suite' in t and 'benchmark' not in t for t in filtered)
all_artifact_only = all(
    'direct' not in t.get('verification_modes', ['artifact'])
    for t in filtered
)
# Only auto-force artifact if ALL tasks are MCP-unique AND none support direct
sys.exit(0 if (all_mcp and all_artifact_only) else 1)
" 2>/dev/null; then
        FULL_CONFIG="mcp-remote-artifact"
        echo "Auto-detected MCP-unique tasks (artifact-only) → using artifact configs ($FULL_CONFIG)"
    fi
fi

load_credentials

enforce_subscription_mode

if [ "$RUN_FULL" = true ] && [ -z "$SOURCEGRAPH_ACCESS_TOKEN" ]; then
    echo "WARNING: MCP mode requested but SOURCEGRAPH_ACCESS_TOKEN not set"
    echo "Skipping MCP runs."
    RUN_FULL=false
fi

ensure_fresh_token_all  # also populates CLAUDE_HOMES[] via setup_multi_accounts
preflight_rate_limits

# Auto-detect PARALLEL_TASKS: Daytona supports 125 concurrent sandboxes,
# local Docker is limited by account sessions.
if [ "$PARALLEL_TASKS" -eq 0 ]; then
    if [ "${HARBOR_ENV:-}" = "daytona" ]; then
        if [ "$DAYTONA_PARALLEL_TASK_CAP" -gt 124 ]; then
            DAYTONA_PARALLEL_TASK_CAP=124
        fi
        PARALLEL_TASKS=$DAYTONA_PARALLEL_TASK_CAP
        echo "Parallel tasks auto-set to $PARALLEL_TASKS (Daytona mode, capped by DAYTONA_PARALLEL_TASK_CAP=${DAYTONA_PARALLEL_TASK_CAP})"
    else
        PARALLEL_TASKS=$PARALLEL_JOBS  # inherits SESSIONS_PER_ACCOUNT * num_accounts from _common.sh
        echo "Parallel tasks auto-set to $PARALLEL_TASKS (local Docker, $SESSIONS_PER_ACCOUNT sessions x ${#CLAUDE_HOMES[@]} accounts)"
    fi
fi

# Derive baseline config and mcp_type values from FULL_CONFIG
BASELINE_CONFIG=$(baseline_config_for "$FULL_CONFIG")
BL_MCP_TYPE=$(config_to_mcp_type "$BASELINE_CONFIG")
FULL_MCP_TYPE=$(config_to_mcp_type "$FULL_CONFIG")

# Strict validation — exit immediately on unknown config names
validate_config_name "$BASELINE_CONFIG"
validate_config_name "$FULL_CONFIG"

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
    # task_dir is relative to benchmarks/ in both formats.
    # Some historical selection entries only have task_id; fallback to
    # benchmarks/{suite}/{task_id} when task_dir is absent.
    task_rel = task.get('task_dir') or f\"{bm}/{task.get('task_id', '')}\"
    if not task_rel or task_rel.endswith('/'):
        continue
    task_dir = 'benchmarks/' + task_rel
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
echo "CodeScaleBench Selected Tasks Runner"
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
    if [ "$SKIP_PREBUILD" = false ]; then
        echo ""
        echo "[DRY RUN] Would pre-build Docker images for: ${!BENCHMARK_COUNTS[*]}"
    fi
    exit 0
fi

# ============================================
# DOCKERFILE VARIANT CHECK
# ============================================
# Verify all tasks have the required Dockerfile variant for the chosen config
# BEFORE asking the user to confirm.
check_dockerfile_variants() {
    DOCKERFILE_MISSING_COUNT=0
    DOCKERFILE_READY_COUNT=0
    DOCKERFILE_WARNINGS=""

    local _is_artifact=false
    [[ "$FULL_CONFIG" == *artifact* ]] && _is_artifact=true

    for bm in $(echo "${!BENCHMARK_TASK_DIRS[@]}" | tr ' ' '\n' | sort); do
        while IFS= read -r task_path; do
            [ -z "$task_path" ] && continue
            local abs_path="$REPO_ROOT/$task_path"
            local task_id
            task_id=$(basename "$task_path")

            # Baseline: needs environment/Dockerfile, or Dockerfile.artifact_baseline for artifact mode
            if [ "$RUN_BASELINE" = true ]; then
                if [ "$_is_artifact" = true ]; then
                    if [ ! -f "${abs_path}/environment/Dockerfile.artifact_baseline" ]; then
                        DOCKERFILE_WARNINGS+="  MISSING: ${task_id} — Dockerfile.artifact_baseline"$'\n'
                        DOCKERFILE_MISSING_COUNT=$(( DOCKERFILE_MISSING_COUNT + 1 ))
                    fi
                    if grep -q "No local repositories are pre-checked out." "${abs_path}/instruction.md"; then
                        DOCKERFILE_WARNINGS+="  INVALID: ${task_id} — baseline-local-artifact requires local repos"$'\n'
                        DOCKERFILE_MISSING_COUNT=$(( DOCKERFILE_MISSING_COUNT + 1 ))
                    fi
                elif [ ! -f "${abs_path}/environment/Dockerfile" ]; then
                    DOCKERFILE_WARNINGS+="  MISSING: ${task_id} — Dockerfile (baseline)"$'\n'
                    DOCKERFILE_MISSING_COUNT=$(( DOCKERFILE_MISSING_COUNT + 1 ))
                fi
            fi

            # Full/MCP: needs the variant Dockerfile
            if [ "$RUN_FULL" = true ]; then
                if [ "$_is_artifact" = true ]; then
                    if [ ! -f "${abs_path}/environment/Dockerfile.artifact_only" ]; then
                        DOCKERFILE_WARNINGS+="  MISSING: ${task_id} — Dockerfile.artifact_only"$'\n'
                        DOCKERFILE_MISSING_COUNT=$(( DOCKERFILE_MISSING_COUNT + 1 ))
                    else
                        DOCKERFILE_READY_COUNT=$(( DOCKERFILE_READY_COUNT + 1 ))
                    fi
                else
                    if [ ! -f "${abs_path}/environment/Dockerfile.sg_only" ]; then
                        DOCKERFILE_WARNINGS+="  MISSING: ${task_id} — Dockerfile.sg_only"$'\n'
                        DOCKERFILE_MISSING_COUNT=$(( DOCKERFILE_MISSING_COUNT + 1 ))
                    else
                        DOCKERFILE_READY_COUNT=$(( DOCKERFILE_READY_COUNT + 1 ))
                    fi
                fi
            fi
        done <<< "$(echo "${BENCHMARK_TASK_DIRS[$bm]}" | grep -v '^$')"
    done
}

# ============================================
# PRE-FLIGHT VERIFICATION
# ============================================
echo "----------------------------------------------"
echo "PRE-FLIGHT VERIFICATION"
echo "----------------------------------------------"
echo ""

# 1. Config pair
echo "Config pair:"
if [ "$RUN_BASELINE" = true ]; then
    echo "  Baseline: $BASELINE_CONFIG (mcp_type=$BL_MCP_TYPE)"
fi
if [ "$RUN_FULL" = true ]; then
    echo "  Full:     $FULL_CONFIG (mcp_type=$FULL_MCP_TYPE)"
fi
echo ""

# 2. Dockerfile variant readiness
check_dockerfile_variants
if [ "$RUN_FULL" = true ]; then
    _variant_name="Dockerfile.sg_only"
    [[ "$FULL_CONFIG" == *artifact* ]] && _variant_name="Dockerfile.artifact_only"
    echo "Dockerfile variants ($_variant_name):"
    echo "  Ready:   $DOCKERFILE_READY_COUNT / $TOTAL_TASKS"
    if [ "$DOCKERFILE_MISSING_COUNT" -gt 0 ]; then
        echo "  MISSING: $DOCKERFILE_MISSING_COUNT"
        echo -e "$DOCKERFILE_WARNINGS"
    fi
    echo ""
fi

# 3. Execution environment readiness
if [ "${HARBOR_ENV:-}" = "daytona" ]; then
    echo "Execution env: Daytona"
    echo "Cost policy:   $DAYTONA_COST_POLICY"
    _cost_guard_cmd=(
        python3 "$REPO_ROOT/scripts/daytona_cost_guard.py" preflight
        --selection-file "$SELECTION_FILE"
        --parallel-tasks "$PARALLEL_TASKS"
        --concurrency "$CONCURRENCY"
        --policy "$DAYTONA_COST_POLICY"
    )
    [ -n "$BENCHMARK_FILTER" ] && _cost_guard_cmd+=(--benchmark "$BENCHMARK_FILTER")
    [ -n "$USE_CASE_CATEGORY_FILTER" ] && _cost_guard_cmd+=(--use-case-category "$USE_CASE_CATEGORY_FILTER")
    [ "$RUN_BASELINE" = true ] && _cost_guard_cmd+=(--config "$BASELINE_CONFIG")
    [ "$RUN_FULL" = true ] && _cost_guard_cmd+=(--config "$FULL_CONFIG")
    if ! "${_cost_guard_cmd[@]}"; then
        echo "BLOCKED: Daytona cost guard rejected this launch."
        exit 1
    fi
    mark_daytona_cost_guard_ready
else
    if timeout 10 docker info >/dev/null 2>&1; then
        echo "Docker:       OK"
    else
        echo "Docker:       FAIL — daemon not responding"
        exit 1
    fi
fi

# 4. Account token freshness
if [ "${#CLAUDE_HOMES[@]}" -gt 0 ]; then
    echo "Accounts:     ${#CLAUDE_HOMES[@]} active"
    for _home_dir in "${CLAUDE_HOMES[@]}"; do
        _creds="${_home_dir}/.claude/.credentials.json"
        if [ -f "$_creds" ]; then
            _remaining=$(python3 -c "
import json, time, sys
try:
    d = json.load(open(sys.argv[1]))
    exp = d.get('claudeAiOauth',{}).get('expiresAt',0)
    rem = int((exp - time.time()*1000) / 60000)
    print(f'{rem} min remaining')
except: print('unknown')
" "$_creds" 2>/dev/null)
            echo "  $(basename "$_home_dir"): $_remaining"
        fi
    done
else
    echo "Accounts:     default (single account)"
fi

# 5. Disk space
_disk_free=$(df -BG --output=avail "$REPO_ROOT" 2>/dev/null | tail -1 | tr -d ' G')
if [ -n "$_disk_free" ] && [ "$_disk_free" -lt 5 ]; then
    echo "Disk space:   FAIL — only ${_disk_free}GB free"
    exit 1
elif [ -n "$_disk_free" ] && [ "$_disk_free" -lt 20 ]; then
    echo "Disk space:   WARN — ${_disk_free}GB free (may run low)"
else
    echo "Disk space:   OK (${_disk_free:-?}GB free)"
fi

# 6. Prebuild status
if [ "${HARBOR_ENV:-}" = "daytona" ]; then
    echo "Prebuild:     skipped (Daytona builds remotely)"
elif [ "$SKIP_PREBUILD" = false ]; then
    echo "Prebuild:     enabled (${!BENCHMARK_COUNTS[*]})"
else
    echo "Prebuild:     SKIPPED (--skip-prebuild)"
fi
echo ""

# 7. Critical blockers — exit before confirmation
if [ "$DOCKERFILE_MISSING_COUNT" -gt 0 ]; then
    echo "BLOCKED: $DOCKERFILE_MISSING_COUNT task(s) missing required Dockerfile variant."
    echo "Fix: Run python3 scripts/generate_sgonly_dockerfiles.py for affected tasks."
    exit 1
fi

echo "----------------------------------------------"
echo "Ready to launch $TOTAL_AGENT_RUNS agent runs ($PARALLEL_TASKS parallel)."
echo ""
if [ "${CSB_SKIP_CONFIRM:-}" = "1" ]; then
    echo "[auto] Skipping confirmation (CSB_SKIP_CONFIRM=1)"
else
    read -r -p "Press Enter to proceed, Ctrl+C to abort... " _
fi
echo ""

# ============================================
# DOCKER IMAGE PRE-BUILD
# ============================================
if [ "$SKIP_PREBUILD" = false ] && [ "${HARBOR_ENV:-}" != "daytona" ]; then
    echo "=== Pre-building Docker images ==="
    ensure_base_images
    for bm in $(echo "${!BENCHMARK_COUNTS[@]}" | tr ' ' '\n' | sort); do
        # Pass selected task IDs so prebuild only builds images for tasks we'll run
        _task_list=$(echo "${BENCHMARK_TASK_IDS[$bm]}" | grep -v '^$' | paste -sd, -)
        prebuild_images "$bm" --tasks "$_task_list"
    done
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
_ACCOUNT_IDX=0  # round-robin index into CLAUDE_HOMES[]

# Advance _ACCOUNT_IDX and set _PICKED_HOME to the next account.
# MUST be called directly (not via $()) to keep index in parent shell.
_pick_next_account() {
    local num=${#CLAUDE_HOMES[@]}
    if [ "$num" -eq 0 ]; then
        _PICKED_HOME="$HOME"
        return
    fi
    _PICKED_HOME="${CLAUDE_HOMES[$_ACCOUNT_IDX]}"
    _ACCOUNT_IDX=$(( (_ACCOUNT_IDX + 1) % num ))
}

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

# Temp dirs created for MCP Dockerfile swap — cleaned up in _drain_pool
_MCP_TEMP_DIRS=()

# Wait for all pending jobs to complete, then clean up temp dirs
_drain_pool() {
    local p
    for p in "${_PIDS[@]}"; do
        wait "$p" 2>/dev/null || true
    done
    _PIDS=()
    # Clean up MCP temp dirs now that all harbor processes are done
    for d in "${_MCP_TEMP_DIRS[@]}"; do
        rm -rf "$d" 2>/dev/null || true
    done
    _MCP_TEMP_DIRS=()
}

# Launch a task PAIR: baseline + full simultaneously for the same task.
# Follows _common.sh's run_paired_configs pattern: both configs run in parallel
# per task so timing is comparable and resource utilization is maximized.
#
# Dockerfile swap logic (determined by VERIFIER_MODE):
#   direct mode:  baseline=original Dockerfile, MCP=Dockerfile.sg_only
#   artifact mode: baseline=Dockerfile.artifact_baseline (local code + sentinel),
#                  MCP=Dockerfile.artifact_only (empty workspace + sentinel).
#                  Both set /tmp/.artifact_only_mode so verifier parses answer.json.
#
# Args: bm task_id task_path bl_jobs_dir full_jobs_dir
_launch_task_pair() {
    local bm="$1" task_id="$2" task_path="$3" bl_jobs_dir="$4" full_jobs_dir="$5"
    local abs_path="$REPO_ROOT/$task_path"

    if [ ! -d "$abs_path" ]; then
        echo "WARNING: Task directory not found: $abs_path"
        return
    fi

    local pair_pids=()
    local _mcp_temp_dir=""
    local _bl_temp_dir=""

    # Determine which Dockerfile variant to use for each config.
    # Note: cannot rely on VERIFIER_MODE because config_to_mcp_type runs in $()
    # subshells (lines 151-152), so its side-effect globals don't propagate.
    local _is_artifact=false
    [[ "$FULL_CONFIG" == *artifact* ]] && _is_artifact=true

    # Launch baseline config
    if [ "$RUN_BASELINE" = true ]; then
        local _bl_task_path="$abs_path"

        # Artifact mode: baseline uses Dockerfile.artifact_baseline (local code + artifact sentinel).
        # Do not fall back to Dockerfile.artifact_only; that changes the run semantics.
        if [ "$_is_artifact" = true ]; then
            local _df_artifact_bl="${abs_path}/environment/Dockerfile.artifact_baseline"
            if [ -f "$_df_artifact_bl" ]; then
                _bl_temp_dir=$(_td=$(mktemp -d "/tmp/bl_${task_id}_XXXXXX") && _td_lower=$(echo "$_td" | tr '[:upper:]' '[:lower:]') && [ "$_td" != "$_td_lower" ] && mv "$_td" "$_td_lower"; echo "${_td_lower:-$_td}")
                cp -a "${abs_path}/." "${_bl_temp_dir}/"
                cp "$_df_artifact_bl" "${_bl_temp_dir}/environment/Dockerfile"
                _bl_task_path="$_bl_temp_dir"
                echo "  [artifact-baseline] Using local-code artifact Dockerfile for baseline: $task_id"
            else
                echo "  ERROR: Missing Dockerfile.artifact_baseline for $task_id"
                continue
            fi
        fi

        _wait_for_slot
        _pick_next_account
        local _bl_home="$_PICKED_HOME"
        (
            export HOME="$_bl_home"
            TASK_SOURCE_DIR="$abs_path" \
            INSTRUCTION_VARIANT="default" \
            DAYTONA_LABEL_RUN_ID="$(basename "$(dirname "$bl_jobs_dir")")" \
            DAYTONA_LABEL_BENCHMARK="$bm" \
            DAYTONA_LABEL_TASK_ID="$task_id" \
            DAYTONA_LABEL_CONFIG="$BASELINE_CONFIG" \
            DAYTONA_LABEL_CATEGORY="$CATEGORY" \
            BASELINE_MCP_TYPE=$BL_MCP_TYPE harbor_run_guarded \
                --path "$_bl_task_path" \
                --agent-import-path "$AGENT_PATH" \
                --model "$MODEL" \
                --jobs-dir "$bl_jobs_dir" \
                -n "$CONCURRENCY" \
                --timeout-multiplier "$TIMEOUT_MULTIPLIER" \
                ${HARBOR_ENV:+--env "$HARBOR_ENV"} \
                ${DAYTONA_OVERRIDE_MEMORY:+--override-memory-mb "$DAYTONA_OVERRIDE_MEMORY"} \
                ${DAYTONA_OVERRIDE_STORAGE:+--override-storage-mb "$DAYTONA_OVERRIDE_STORAGE"} \
                2>&1 | tee -a "${bl_jobs_dir}.log" \
                || echo "WARNING: $BASELINE_CONFIG failed: $task_id"
        ) &
        pair_pids+=("$!")
        _PIDS+=("$!")
        echo "  [$BASELINE_CONFIG] Started $task_id (PID ${_PIDS[-1]}, ${#_PIDS[@]}/${PARALLEL_TASKS} slots, HOME=$(basename "$_bl_home"))"
        # Stagger launches by 2s to avoid Harbor timestamp-based job directory collisions
        sleep 2
    fi

    # Launch full/MCP config
    if [ "$RUN_FULL" = true ]; then
        local _mcp_task_path="$abs_path"

        if [ "$_is_artifact" = true ]; then
            # Artifact mode: use Dockerfile.artifact_only (full repo + artifact sentinel)
            local _df_artifact="${abs_path}/environment/Dockerfile.artifact_only"
            if [ -f "$_df_artifact" ]; then
                _mcp_temp_dir=$(_td=$(mktemp -d "/tmp/mcp_${task_id}_XXXXXX") && _td_lower=$(echo "$_td" | tr '[:upper:]' '[:lower:]') && [ "$_td" != "$_td_lower" ] && mv "$_td" "$_td_lower"; echo "${_td_lower:-$_td}")
                cp -a "${abs_path}/." "${_mcp_temp_dir}/"
                cp "${_mcp_temp_dir}/environment/Dockerfile.artifact_only" "${_mcp_temp_dir}/environment/Dockerfile"
                _mcp_task_path="$_mcp_temp_dir"
                echo "  [artifact] Using artifact Dockerfile for MCP config: $task_id"
            else
                echo "  WARNING: No Dockerfile.artifact_only for $task_id — MCP verifier won't parse answer.json"
            fi
        else
            # Direct mode: use Dockerfile.sg_only (empty workspace, agent uses MCP)
            local _df_sgonly="${abs_path}/environment/Dockerfile.sg_only"
            if [ -f "$_df_sgonly" ]; then
                _mcp_temp_dir=$(_td=$(mktemp -d "/tmp/mcp_${task_id}_XXXXXX") && _td_lower=$(echo "$_td" | tr '[:upper:]' '[:lower:]') && [ "$_td" != "$_td_lower" ] && mv "$_td" "$_td_lower"; echo "${_td_lower:-$_td}")
                cp -a "${abs_path}/." "${_mcp_temp_dir}/"
                cp "${_mcp_temp_dir}/environment/Dockerfile.sg_only" "${_mcp_temp_dir}/environment/Dockerfile"
                _mcp_task_path="$_mcp_temp_dir"
                echo "  [sg_only] Using empty-workspace Dockerfile for MCP config: $task_id"
            else
                echo "  WARNING: No Dockerfile.sg_only for $task_id — MCP will have local source access"
            fi
        fi

        # Extract SOURCEGRAPH_REPOS from the active Dockerfile so the agent
        # preamble can scope MCP queries to version-pinned mirrors.
        # The container exec fallback in setup() is unreliable (empty trial.log
        # observed), so we pass the value as a host env var directly.
        local _sg_repos=""
        _sg_repos=$(grep -oP '(?<=ENV SOURCEGRAPH_REPOS=")[^"]+' "${_mcp_task_path}/environment/Dockerfile" 2>/dev/null || true)

        _wait_for_slot
        _pick_next_account
        local _full_home="$_PICKED_HOME"
        local _instruction_variant="mcp"
        if [[ "$FULL_CONFIG" == *scip* ]]; then
            _instruction_variant="mcp_scip"
        fi

        (
            export HOME="$_full_home"
            TASK_SOURCE_DIR="$abs_path" \
            INSTRUCTION_VARIANT="$_instruction_variant" \
            SOURCEGRAPH_REPOS="$_sg_repos" \
            DAYTONA_LABEL_RUN_ID="$(basename "$(dirname "$full_jobs_dir")")" \
            DAYTONA_LABEL_BENCHMARK="$bm" \
            DAYTONA_LABEL_TASK_ID="$task_id" \
            DAYTONA_LABEL_CONFIG="$FULL_CONFIG" \
            DAYTONA_LABEL_CATEGORY="$CATEGORY" \
            BASELINE_MCP_TYPE=$FULL_MCP_TYPE harbor_run_guarded \
                --path "$_mcp_task_path" \
                --agent-import-path "$AGENT_PATH" \
                --model "$MODEL" \
                --jobs-dir "$full_jobs_dir" \
                -n "$CONCURRENCY" \
                --timeout-multiplier "$TIMEOUT_MULTIPLIER" \
                ${HARBOR_ENV:+--env "$HARBOR_ENV"} \
                ${DAYTONA_OVERRIDE_MEMORY:+--override-memory-mb "$DAYTONA_OVERRIDE_MEMORY"} \
                ${DAYTONA_OVERRIDE_STORAGE:+--override-storage-mb "$DAYTONA_OVERRIDE_STORAGE"} \
                2>&1 | tee -a "${full_jobs_dir}.log" \
                || echo "WARNING: $FULL_CONFIG failed: $task_id"
        ) &
        pair_pids+=("$!")
        _PIDS+=("$!")
        echo "  [$FULL_CONFIG] Started $task_id (PID ${_PIDS[-1]}, ${#_PIDS[@]}/${PARALLEL_TASKS} slots, HOME=$(basename "$_full_home"))"
        sleep 2
    fi

    # Track temp dirs for cleanup in _drain_pool (after all harbor processes finish).
    # Cannot use background watcher because wait() only works for child processes.
    if [ -n "$_mcp_temp_dir" ]; then
        _MCP_TEMP_DIRS+=("$_mcp_temp_dir")
    fi
    if [ -n "$_bl_temp_dir" ]; then
        _MCP_TEMP_DIRS+=("$_bl_temp_dir")
    fi
}

# ============================================
# MAIN EXECUTION — paired task submission across all benchmarks
# Baseline + MCP launch simultaneously per task (task-paired, not mode-sequential).
# This matches _common.sh's run_paired_configs pattern.
# ============================================

# Create all jobs_dirs upfront for post-processing reference
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

echo ""
echo "=== Submitting paired tasks ($BASELINE_CONFIG + $FULL_CONFIG) ==="

for bm in $(echo "${!BENCHMARK_COUNTS[@]}" | tr ' ' '\n' | sort); do
    task_ids=$(echo "${BENCHMARK_TASK_IDS[$bm]}" | grep -v '^$')
    task_dirs=$(echo "${BENCHMARK_TASK_DIRS[$bm]}" | grep -v '^$')

    while IFS= read -r task_id && IFS= read -r task_path <&3; do
        [ -z "$task_id" ] && continue

        # Skip if both configs already completed
        bl_done=false; full_done=false
        [ "$RUN_BASELINE" = true ] && is_task_completed "${BL_JOBS_DIRS[$bm]:-}" "$task_id" && bl_done=true
        [ "$RUN_FULL" = true ]    && is_task_completed "${FULL_JOBS_DIRS[$bm]:-}" "$task_id" && full_done=true
        if [ "$bl_done" = true ] && [ "$full_done" = true ]; then
            echo "  SKIP (both completed): $task_id"
            continue
        fi

        _launch_task_pair "$bm" "$task_id" "$task_path" \
            "${BL_JOBS_DIRS[$bm]:-}" "${FULL_JOBS_DIRS[$bm]:-}"
    done <<< "$task_ids" 3<<< "$task_dirs"
done

echo ""
echo "=== Waiting for all paired tasks to complete... ==="
_drain_pool
echo "=== All tasks complete ==="

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
