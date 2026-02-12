#!/bin/bash
# Baseline Rerun Script — Opus 4.6 Model Alignment
#
# Reruns baseline (no MCP) for tasks whose latest baseline result is still Opus 4.5.
# Covers 8 suites (~76 tasks). Suites already fully on 4.6 are excluded:
#   ccb_crossrepo, ccb_dependeval, ccb_k8sdocs, ccb_largerepo, ccb_tac
#
# Usage:
#   ./configs/baseline_rerun_opus46.sh [OPTIONS]
#
# Options:
#   --parallel N     Number of parallel task subshells (default: auto from accounts)
#   --dry-run        Print task lists without running
#   --suite SUITE    Run only a specific suite (e.g. ccb_pytorch)
#
# Estimated cost: ~$200 (runs ALL selected tasks per suite; MANIFEST timestamp
#   dedup keeps newest result. Slightly overruns 76-task target but ensures clean slate.)
#   Use --suite to run one suite at a time if needed.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

AGENT_DIR="${AGENT_DIR:-$HOME/evals/custom_agents/agents/claudecode}"
export PYTHONPATH="${AGENT_DIR}:$(pwd):$PYTHONPATH"

source "$SCRIPT_DIR/_common.sh"

if [ -f ~/evals/.env.local ]; then
    source ~/evals/.env.local
fi

enforce_subscription_mode

AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
MODEL="anthropic/claude-opus-4-6"
CONCURRENCY=2
TIMEOUT_MULTIPLIER=10
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SELECTION_FILE="$SCRIPT_DIR/selected_benchmark_tasks.json"
DRY_RUN=false
SUITE_FILTER=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --parallel)
            PARALLEL_JOBS="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --suite)
            SUITE_FILTER="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

setup_dual_accounts

if ! check_token_health; then
    echo "FATAL: Token health check failed. Run:"
    echo "  python3 scripts/headless_login.py --all-accounts"
    exit 1
fi

echo "=============================================="
echo "Baseline Rerun — Opus 4.6 Model Alignment"
echo "=============================================="
echo "Model: ${MODEL}"
echo "Parallel jobs: ${PARALLEL_JOBS}"
echo "Dry run: ${DRY_RUN}"
[ -n "$SUITE_FILTER" ] && echo "Suite filter: ${SUITE_FILTER}"
echo ""

# ============================================
# SUITE DEFINITIONS
# ============================================
# Each suite: benchmark_name, tasks_dir, run_dir_prefix, task_source
# task_source: "json" (load from selected_benchmark_tasks.json) or "dataset" (harbor --dataset)

BENCHMARKS_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks"

# Helper: load task IDs for a benchmark from selected_benchmark_tasks.json
load_task_ids() {
    local benchmark=$1
    python3 -c "
import json
tasks = json.load(open('$SELECTION_FILE'))['tasks']
for t in tasks:
    if t['benchmark'] == '$benchmark':
        print(t['task_id'])
"
}

# Helper: run baseline for --path tasks
run_path_baseline() {
    local suite=$1
    local tasks_dir=$2
    local jobs_dir=$3
    shift 3
    local task_ids=("$@")

    ensure_fresh_token_all
    mkdir -p "$jobs_dir"

    _run_single() {
        local task_id=$1
        local task_home=$2
        local task_path="${tasks_dir}/${task_id}"

        if [ ! -d "$task_path" ]; then
            echo "SKIP: Task directory not found: $task_path"
            return 0
        fi

        echo "  [baseline] ${suite}/${task_id} [HOME=$task_home]"
        BASELINE_MCP_TYPE=none harbor run \
            --path "$task_path" \
            --agent-import-path "$AGENT_PATH" \
            --model "$MODEL" \
            --jobs-dir "$jobs_dir" \
            -n $CONCURRENCY \
            --timeout-multiplier $TIMEOUT_MULTIPLIER \
            2>&1 | tee "${jobs_dir}/${task_id}.log" || true
    }

    run_canary_then_batch task_ids _run_single "$jobs_dir" "baseline"
    validate_and_report "$jobs_dir" "baseline"
}

# Helper: run baseline for --dataset swebenchpro tasks (sequential due to timestamp collision)
run_dataset_baseline() {
    local jobs_dir=$1
    shift
    local task_ids=("$@")

    ensure_fresh_token_all
    mkdir -p "$jobs_dir"

    for task_id in "${task_ids[@]}"; do
        echo "  [baseline] swebenchpro/${task_id}"
        BASELINE_MCP_TYPE=none harbor run \
            --dataset swebenchpro \
            -t "$task_id" \
            --agent-import-path "$AGENT_PATH" \
            --model "$MODEL" \
            --jobs-dir "$jobs_dir" \
            -n $CONCURRENCY \
            --timeout-multiplier $TIMEOUT_MULTIPLIER \
            2>&1 | tee "${jobs_dir}/${task_id}.log" || true

        # 2-second stagger to avoid timestamp collision
        sleep 2
    done

    validate_and_report "$jobs_dir" "baseline"
}

# ============================================
# SUITE EXECUTION
# ============================================
run_suite() {
    local suite=$1
    local tasks_dir=$2
    local mode=$3  # "path" or "dataset"

    if [ -n "$SUITE_FILTER" ] && [ "$SUITE_FILTER" != "$suite" ]; then
        return 0
    fi

    readarray -t TASK_IDS < <(load_task_ids "$suite")
    local count=${#TASK_IDS[@]}

    if [ "$count" -eq 0 ]; then
        echo "SKIP: No tasks found for $suite"
        return 0
    fi

    local jobs_dir="runs/official/${suite#ccb_}_baseline_rerun_opus_${TIMESTAMP}/baseline"

    echo ""
    echo ">>> ${suite} (${count} tasks)"
    echo "    Jobs: ${jobs_dir}"

    if [ "$DRY_RUN" = true ]; then
        for t in "${TASK_IDS[@]}"; do echo "    - $t"; done
        return 0
    fi

    if [ "$mode" = "dataset" ]; then
        run_dataset_baseline "$jobs_dir" "${TASK_IDS[@]}"
    else
        run_path_baseline "$suite" "$tasks_dir" "$jobs_dir" "${TASK_IDS[@]}"
    fi
}

# Suites that need baseline reruns (all tasks within each)
# Suites NOT listed here are already fully on Opus 4.6 baseline:
#   ccb_crossrepo, ccb_dependeval, ccb_k8sdocs, ccb_largerepo, ccb_tac

run_suite "ccb_swebenchpro"   ""                                      "dataset"
run_suite "ccb_pytorch"       "${BENCHMARKS_DIR}/ccb_pytorch"          "path"
run_suite "ccb_locobench"     "${BENCHMARKS_DIR}/ccb_locobench/tasks"  "path"
run_suite "ccb_repoqa"        "${BENCHMARKS_DIR}/ccb_repoqa/tasks"     "path"
run_suite "ccb_dibench"       "${BENCHMARKS_DIR}/ccb_dibench"          "path"
run_suite "ccb_linuxflbench"  "${BENCHMARKS_DIR}/ccb_linuxflbench"     "path"
run_suite "ccb_codereview"    "${BENCHMARKS_DIR}/ccb_codereview"       "path"
run_suite "ccb_sweperf"       "${BENCHMARKS_DIR}/ccb_sweperf/tasks"    "path"

echo ""
echo "=============================================="
echo "Baseline Rerun Complete"
echo "=============================================="
echo "Regenerate MANIFEST: python3 scripts/generate_manifest.py"
