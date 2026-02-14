#!/bin/bash
# Universal Paired Rerun — All Benchmarks, 2 Configs (Baseline + SG_full)
#
# Runs ALL benchmark tasks from selected_benchmark_tasks.json with paired execution:
# for each task, Baseline and SG_full launch concurrently so they experience
# identical VM load conditions. This eliminates load-as-confound.
#
# Design:
#   - Each "job slot" runs ONE task with BOTH configs (BL + SF) simultaneously
#   - Each paired slot uses 2 sessions from the same account
#   - 3 accounts × 4 sessions = 12 sessions → 6 concurrent paired tasks
#   - Tasks are interleaved across benchmarks for balanced load
#
# Usage:
#   ./configs/universal_paired_rerun.sh                    # Full run (all tasks)
#   ./configs/universal_paired_rerun.sh --benchmark ccb_pytorch  # Single benchmark
#   ./configs/universal_paired_rerun.sh --dry-run          # Show task plan, don't run
#   ./configs/universal_paired_rerun.sh --parallel 4       # Override paired slots
#   ./configs/universal_paired_rerun.sh --baseline-only    # Only baseline (no SF)
#   ./configs/universal_paired_rerun.sh --full-only        # Only SG_full (no BL)
#
# Prerequisites:
#   - ~/evals/.env.local with USE_SUBSCRIPTION=true
#   - SOURCEGRAPH_ACCESS_TOKEN in .env.local
#   - 3 accounts in ~/.claude-homes/account{1,2,3}/

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# Agent module
AGENT_DIR="${AGENT_DIR:-$HOME/evals/custom_agents/agents/claudecode}"
export PYTHONPATH="${AGENT_DIR}:$(pwd):$PYTHONPATH"

# Shared infrastructure
source "$SCRIPT_DIR/_common.sh"

# ============================================
# LOAD CREDENTIALS
# ============================================
if [ -f ~/evals/.env.local ]; then
    echo "Loading credentials from ~/evals/.env.local..."
    source ~/evals/.env.local
else
    echo "ERROR: ~/evals/.env.local not found"
    exit 1
fi

enforce_subscription_mode

# ============================================
# CONFIGURATION
# ============================================
MODEL="${MODEL:-anthropic/claude-opus-4-6}"
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
TIMEOUT_MULTIPLIER=10
CONCURRENCY=1          # Trials per task (1 = single attempt)
CATEGORY="${CATEGORY:-official}"
BENCHMARK_FILTER=""    # Empty = all benchmarks
ONLY_TASKS=""          # Empty = all tasks; space-separated list = only these
DRY_RUN=false
RUN_BASELINE=true
RUN_FULL=true
# Skip known-broken tasks
SKIP_TASKS="sgt-025"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --benchmark)
            BENCHMARK_FILTER="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --parallel)
            PARALLEL_JOBS="$2"
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
        --skip)
            SKIP_TASKS="$SKIP_TASKS $2"
            shift 2
            ;;
        --only)
            ONLY_TASKS="$ONLY_TASKS $2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--benchmark SUITE] [--dry-run] [--parallel N] [--baseline-only] [--full-only] [--model MODEL] [--skip TASK_ID] [--only TASK_ID]"
            exit 1
            ;;
    esac
done

# ============================================
# ACCOUNT SETUP
# ============================================
setup_multi_accounts
ensure_fresh_token_all

if [ -n "$SOURCEGRAPH_ACCESS_TOKEN" ]; then
    echo "SOURCEGRAPH_ACCESS_TOKEN: set (${#SOURCEGRAPH_ACCESS_TOKEN} chars)"
else
    echo "WARNING: SOURCEGRAPH_ACCESS_TOKEN not set — SG_full runs will fail"
fi

# For paired execution: each task uses 2 sessions (BL + SF)
# So max concurrent paired tasks = total_sessions / 2
NUM_SESSIONS=$(( SESSIONS_PER_ACCOUNT * ${#CLAUDE_HOMES[@]} ))
if [ "$PARALLEL_JOBS" -eq 0 ] || [ "$PARALLEL_JOBS" -gt $(( NUM_SESSIONS / 2 )) ]; then
    PARALLEL_JOBS=$(( NUM_SESSIONS / 2 ))
fi
echo "Paired parallel slots: $PARALLEL_JOBS (each uses 2 sessions: BL + SF)"

# ============================================
# TASK LOADING
# ============================================
SELECTION_FILE="$SCRIPT_DIR/selected_benchmark_tasks.json"
if [ ! -f "$SELECTION_FILE" ]; then
    echo "ERROR: selected_benchmark_tasks.json not found"
    exit 1
fi

# Build task list with metadata using Python
# Output format: task_id|benchmark|task_dir|sg_repo_name (one per line)
TASK_LIST=$(BENCHMARK_FILTER="$BENCHMARK_FILTER" SKIP_TASKS="$SKIP_TASKS" ONLY_TASKS="$ONLY_TASKS" python3 << 'PYEOF'
import json, os

selection = json.load(open("configs/selected_benchmark_tasks.json"))
mirror_map = json.load(open("configs/instance_to_mirror.json"))

benchmark_filter = os.environ.get("BENCHMARK_FILTER", "")
skip_tasks = set(os.environ.get("SKIP_TASKS", "").split())
only_tasks = set(os.environ.get("ONLY_TASKS", "").split())
only_tasks.discard("")  # Remove empty string if ONLY_TASKS was empty

# PyTorch SG repo name mapping (commit-specific mirrors)
pytorch_sg_repos = {
    "sgt-001": "sg-benchmarks/pytorch--ca246612",
    "sgt-002": "sg-benchmarks/pytorch--ca246612",
    "sgt-003": "sg-benchmarks/pytorch--d18007a1",
    "sgt-005": "sg-benchmarks/pytorch--ca246612",
    "sgt-008": "sg-benchmarks/pytorch--863edc78",
    "sgt-009": "sg-benchmarks/pytorch--863edc78",
    "sgt-010": "sg-benchmarks/pytorch--5811a8d7",
    "sgt-012": "sg-benchmarks/pytorch--e3e93c71",
    "sgt-014": "sg-benchmarks/pytorch--cbe1a35d",
    "sgt-016": "sg-benchmarks/pytorch--cbe1a35d",
    "sgt-021": "sg-benchmarks/pytorch--cbe1a35d",
    "sgt-025": "sg-benchmarks/pytorch--e8ca8cc3",
}

# LoCoBench SG repo mapping (project_id → locobench-{prefix})
locobench_sg_repos = {}
if "locobench" in mirror_map:
    lb = mirror_map["locobench"]
    if isinstance(lb, dict):
        for task_id, info in lb.items():
            if isinstance(info, dict) and "mirror_name" in info:
                locobench_sg_repos[task_id] = info["mirror_name"]

def get_sg_repo(task):
    """Resolve Sourcegraph repo name for a task."""
    tid = task["task_id"]
    bench = task["benchmark"]

    # PyTorch: commit-specific mirrors
    if bench == "ccb_pytorch":
        return pytorch_sg_repos.get(tid, "")

    # LoCoBench: locobench-{project_id} mirrors
    if bench == "ccb_locobench":
        if tid in locobench_sg_repos:
            return locobench_sg_repos[tid]
        # Derive project_id by stripping task-type suffix
        for suffix in ["_architectural_understanding_expert_01", "_cross_file_refactoring_expert_01", "_bug_investigation_expert_01"]:
            if tid.endswith(suffix):
                project_id = tid[:-len(suffix)]
                return f"sg-benchmarks/locobench-{project_id}"
        return ""

    # SWE-bench Pro: look up in mirror_map.swebenchpro.tasks
    if bench == "ccb_swebenchpro":
        swp = mirror_map.get("swebenchpro", {}).get("tasks", {})
        # Task IDs in mirror_map use different casing — try exact then case-insensitive
        for key, info in swp.items():
            if tid.lower().replace("-", "_").startswith(key.lower().replace("-", "_")[:40]):
                return info.get("mirror_name", "")
        # Fallback: use repo field from selection
        repo = task.get("repo", "")
        return f"sg-benchmarks/{repo.split('/')[-1]}" if repo else ""

    # K8s Docs
    if bench == "ccb_k8sdocs":
        return task.get("repo", "sg-benchmarks/kubernetes--stripped")

    # TAC: look up in mirror_map
    if bench == "ccb_tac":
        tac_map = mirror_map.get("tac", {})
        if isinstance(tac_map, dict) and tid in tac_map:
            return tac_map[tid].get("mirror_name", "")
        return ""

    # LinuxFLBench: commit-specific Linux kernel mirrors
    if bench == "ccb_linuxflbench":
        lfl_map = mirror_map.get("linuxflbench", {}).get("tasks", {})
        if tid in lfl_map:
            return lfl_map[tid].get("mirror_name", "")
        return "torvalds/linux"  # Fallback to public repo

    # LargeRepo
    if bench == "ccb_largerepo":
        repo = task.get("repo", "")
        return repo  # Use public GitHub repo directly

    # DependEval: look up by task_dir key
    if bench == "ccb_dependeval":
        td = task.get("task_dir", "")
        if td in mirror_map:
            return mirror_map[td]
        return ""

    # Other benchmarks: use repo field from selection, fall back to public
    repo = task.get("repo", "")
    if repo:
        return repo
    return ""

# Exclude investigation (not part of BL vs MCP comparison)
excluded_benchmarks = {"ccb_investigation"}

for task in selection["tasks"]:
    bench = task["benchmark"]
    tid = task["task_id"]

    if bench in excluded_benchmarks:
        continue
    if benchmark_filter and bench != benchmark_filter:
        continue
    if tid in skip_tasks:
        continue
    if only_tasks and tid not in only_tasks:
        continue

    task_dir = task.get("task_dir", "")
    sg_repo = get_sg_repo(task)
    sdlc_phase = task.get("sdlc_phase", "")
    category = task.get("category", "")

    print(f"{tid}|{bench}|{task_dir}|{sg_repo}|{sdlc_phase}|{category}")
PYEOF
)

if [ -z "$TASK_LIST" ]; then
    echo "ERROR: No tasks found (filter: ${BENCHMARK_FILTER:-all})"
    exit 1
fi

# Parse into arrays
readarray -t ALL_TASK_IDS < <(echo "$TASK_LIST" | cut -d'|' -f1)
readarray -t ALL_BENCHMARKS < <(echo "$TASK_LIST" | cut -d'|' -f2)
readarray -t ALL_TASK_DIRS < <(echo "$TASK_LIST" | cut -d'|' -f3)
readarray -t ALL_SG_REPOS < <(echo "$TASK_LIST" | cut -d'|' -f4)
readarray -t ALL_SDLC_PHASES < <(echo "$TASK_LIST" | cut -d'|' -f5)
readarray -t ALL_CATEGORIES < <(echo "$TASK_LIST" | cut -d'|' -f6)

# Build associative arrays for lookup
declare -A TASK_BENCHMARK TASK_DIR TASK_SG_REPO TASK_SDLC_PHASE TASK_CATEGORY
for i in "${!ALL_TASK_IDS[@]}"; do
    TASK_BENCHMARK["${ALL_TASK_IDS[$i]}"]="${ALL_BENCHMARKS[$i]}"
    TASK_DIR["${ALL_TASK_IDS[$i]}"]="${ALL_TASK_DIRS[$i]}"
    TASK_SG_REPO["${ALL_TASK_IDS[$i]}"]="${ALL_SG_REPOS[$i]}"
    TASK_SDLC_PHASE["${ALL_TASK_IDS[$i]}"]="${ALL_SDLC_PHASES[$i]}"
    TASK_CATEGORY["${ALL_TASK_IDS[$i]}"]="${ALL_CATEGORIES[$i]}"
done

# ============================================
# RUN DIRECTORY
# ============================================
_model_lower=$(echo "$MODEL" | awk -F/ '{print $NF}' | tr '[:upper:]' '[:lower:]')
case "$_model_lower" in
    *opus*)   MODEL_SHORT="opus" ;;
    *sonnet*) MODEL_SHORT="sonnet" ;;
    *haiku*)  MODEL_SHORT="haiku" ;;
    *)        MODEL_SHORT=$(echo "$_model_lower" | tr -d '-' | cut -c1-8) ;;
esac

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILTER_TAG=""
[ -n "$BENCHMARK_FILTER" ] && FILTER_TAG="_$(echo "$BENCHMARK_FILTER" | sed 's/ccb_//')"
JOBS_BASE="runs/${CATEGORY}/paired_rerun${FILTER_TAG}_${MODEL_SHORT}_${TIMESTAMP}"

echo ""
echo "=============================================="
echo "Universal Paired Rerun"
echo "=============================================="
echo "Model:      $MODEL"
echo "Tasks:      ${#ALL_TASK_IDS[@]}"
echo "Configs:    $([ "$RUN_BASELINE" = true ] && echo -n "baseline ")$([ "$RUN_FULL" = true ] && echo -n "sourcegraph_full")"
echo "Parallel:   $PARALLEL_JOBS paired slots (${NUM_SESSIONS} sessions across ${#CLAUDE_HOMES[@]} accounts)"
echo "Output:     $JOBS_BASE"
echo "Filter:     ${BENCHMARK_FILTER:-all benchmarks}"
echo "Skipping:   ${SKIP_TASKS}"
echo ""

# Show task breakdown by benchmark
echo "Task breakdown:"
python3 -c "
from collections import Counter
tasks = '''${TASK_LIST}'''.strip().split('\n')
counts = Counter(t.split('|')[1] for t in tasks if t)
for bench, count in sorted(counts.items()):
    print(f'  {bench}: {count}')
print(f'  TOTAL: {len(tasks)}')
"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo "DRY RUN — Task plan:"
    for i in "${!ALL_TASK_IDS[@]}"; do
        echo "  ${ALL_TASK_IDS[$i]} | ${ALL_BENCHMARKS[$i]} | SG_REPO=${ALL_SG_REPOS[$i]:-none} | SDLC=${ALL_SDLC_PHASES[$i]:-?}"
    done
    echo ""
    echo "Would create: $JOBS_BASE/{baseline,sourcegraph_full}/"
    echo "Would run ${#ALL_TASK_IDS[@]} tasks × 2 configs = $(( ${#ALL_TASK_IDS[@]} * 2 )) harbor runs"
    echo "Estimated time: ~$(( ${#ALL_TASK_IDS[@]} / PARALLEL_JOBS * 30 )) minutes"
    exit 0
fi

# ============================================
# CREATE OUTPUT DIRECTORIES
# ============================================
mkdir -p "$JOBS_BASE/baseline" "$JOBS_BASE/sourcegraph_full"

# ============================================
# PAIRED TASK RUNNER
# ============================================
# Each call runs BL + SF concurrently for one task.
_run_paired_task() {
    local task_id=$1
    local task_home=$2

    local task_dir="${TASK_DIR[$task_id]}"
    local sg_repo="${TASK_SG_REPO[$task_id]}"
    local benchmark="${TASK_BENCHMARK[$task_id]}"
    local sdlc_phase="${TASK_SDLC_PHASE[$task_id]}"
    local category="${TASK_CATEGORY[$task_id]}"
    local task_path="benchmarks/$task_dir"

    if [ ! -d "$task_path" ]; then
        echo "ERROR: Task directory not found: $task_path (task=$task_id)"
        return 1
    fi

    echo "[$task_id] Starting paired run (benchmark=$benchmark, sg_repo=${sg_repo:-none})"

    local bl_pid=0
    local sf_pid=0

    # Set SG repo name for this task
    if [ -n "$sg_repo" ]; then
        export SOURCEGRAPH_REPO_NAME="$sg_repo"
    else
        unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
    fi

    # Launch Baseline
    if [ "$RUN_BASELINE" = true ]; then
        (
            BASELINE_MCP_TYPE=none harbor run \
                --path "$task_path" \
                --agent-import-path "$AGENT_PATH" \
                --model "$MODEL" \
                --jobs-dir "$JOBS_BASE/baseline" \
                -n $CONCURRENCY \
                --timeout-multiplier $TIMEOUT_MULTIPLIER \
                2>&1 | tee "$JOBS_BASE/baseline/${task_id}.log"
        ) &
        bl_pid=$!
        echo "  [$task_id] Baseline launched (PID $bl_pid)"
        sleep 2  # Stagger to avoid Harbor timestamp collision
    fi

    # Launch SG_full
    if [ "$RUN_FULL" = true ]; then
        (
            BASELINE_MCP_TYPE=sourcegraph_full TASK_SDLC_PHASE="$sdlc_phase" TASK_CATEGORY="$category" harbor run \
                --path "$task_path" \
                --agent-import-path "$AGENT_PATH" \
                --model "$MODEL" \
                --jobs-dir "$JOBS_BASE/sourcegraph_full" \
                -n $CONCURRENCY \
                --timeout-multiplier $TIMEOUT_MULTIPLIER \
                2>&1 | tee "$JOBS_BASE/sourcegraph_full/${task_id}.log"
        ) &
        sf_pid=$!
        echo "  [$task_id] SG_full launched (PID $sf_pid)"
    fi

    # Wait for both to complete
    local bl_exit=0 sf_exit=0
    if [ "$bl_pid" -gt 0 ]; then
        wait $bl_pid || bl_exit=$?
    fi
    if [ "$sf_pid" -gt 0 ]; then
        wait $sf_pid || sf_exit=$?
    fi

    if [ "$bl_exit" -ne 0 ] || [ "$sf_exit" -ne 0 ]; then
        echo "  [$task_id] WARNING: BL exit=$bl_exit, SF exit=$sf_exit"
        return 1
    fi

    echo "  [$task_id] Paired run complete"
    return 0
}

# ============================================
# MAIN EXECUTION
# ============================================
echo ""
echo "Starting paired execution at $(date -u +%Y-%m-%dT%H:%M:%SZ)..."
echo ""

# Disable fail-fast for the full suite — we want max coverage
export FAIL_FAST=false

# Use the parallel runner with paired task function
run_tasks_parallel ALL_TASK_IDS _run_paired_task || true

# ============================================
# POST-RUN
# ============================================
echo ""
echo "=============================================="
echo "Paired Rerun Complete!"
echo "=============================================="
echo "Results: $JOBS_BASE"
echo "  Baseline:         $JOBS_BASE/baseline/"
echo "  SG_full:          $JOBS_BASE/sourcegraph_full/"
echo ""
echo "Next steps:"
echo "  1. python3 scripts/generate_manifest.py"
echo "  2. python3 scripts/aggregate_status.py --runs-dir $JOBS_BASE"
echo "  3. python3 scripts/compare_configs.py"
echo ""
echo "Finished at $(date -u +%Y-%m-%dT%H:%M:%SZ)"
