#!/bin/bash
# Scaffold: GitHub MCP comparison for Copilot vs Codex agents.
#
# Runs selected tasks across four variants:
#   1) copilot_baseline   (BASELINE_MCP_TYPE=none)
#   2) copilot_github     (BASELINE_MCP_TYPE=github_full)
#   3) codex_baseline     (BASELINE_MCP_TYPE=none)
#   4) codex_github       (BASELINE_MCP_TYPE=github_full)
#
# This script is a scaffold for agent/harness expansion work. It assumes
# corresponding Harbor agent import paths exist in your external agent repo.
#
# Usage:
#   ./configs/github_copilot_codex_compare.sh --benchmark ccb_crossrepo --dry-run
#   ./configs/github_copilot_codex_compare.sh --benchmark ccb_crossrepo --execute
#
# Required env (example):
#   COPILOT_AGENT_PATH=agents.copilot_driver_agent:CopilotDriverAgent
#   CODEX_AGENT_PATH=agents.codex_driver_agent:CodexDriverAgent
#   GITHUB_MCP_TOKEN=<token>    # if your github MCP mode requires it

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
cd "$REPO_ROOT"

AGENT_DIR="${AGENT_DIR:-$HOME/evals/custom_agents/agents/claudecode}"
export PYTHONPATH="${AGENT_DIR}:$(pwd):$PYTHONPATH"

source "$SCRIPT_DIR/_common.sh"

SELECTION_FILE="$REPO_ROOT/configs/selected_benchmark_tasks.json"
BENCHMARK_FILTER=""
CATEGORY="${CATEGORY:-experimental}"
CONCURRENCY=1
TIMEOUT_MULTIPLIER=10
MODEL_COPILOT="${MODEL_COPILOT:-anthropic/claude-opus-4-6}"
MODEL_CODEX="${MODEL_CODEX:-anthropic/claude-opus-4-6}"
GITHUB_MCP_MODE="${GITHUB_MCP_MODE:-github_full}"
DRY_RUN=true
EXECUTE=false

COPILOT_AGENT_PATH="${COPILOT_AGENT_PATH:-agents.copilot_driver_agent:CopilotDriverAgent}"
CODEX_AGENT_PATH="${CODEX_AGENT_PATH:-agents.codex_driver_agent:CodexDriverAgent}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --benchmark)
            BENCHMARK_FILTER="$2"
            shift 2
            ;;
        --category)
            CATEGORY="$2"
            shift 2
            ;;
        --concurrency)
            CONCURRENCY="$2"
            shift 2
            ;;
        --model-copilot)
            MODEL_COPILOT="$2"
            shift 2
            ;;
        --model-codex)
            MODEL_CODEX="$2"
            shift 2
            ;;
        --github-mcp-mode)
            GITHUB_MCP_MODE="$2"
            shift 2
            ;;
        --execute)
            EXECUTE=true
            DRY_RUN=false
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            EXECUTE=false
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

if [ ! -f "$SELECTION_FILE" ]; then
    echo "ERROR: $SELECTION_FILE not found"
    exit 1
fi

if [ -f ~/evals/.env.local ]; then
    source ~/evals/.env.local
fi

enforce_subscription_mode
ensure_fresh_token
setup_multi_accounts

if [ -z "${GITHUB_MCP_TOKEN:-}" ]; then
    echo "WARNING: GITHUB_MCP_TOKEN is not set. github MCP variants may fail."
fi

readarray -t TASK_ROWS < <(python3 -c "
import json
sel = json.load(open('$SELECTION_FILE'))
f = '$BENCHMARK_FILTER'
for t in sel['tasks']:
    if f and t['benchmark'] != f:
        continue
    print(f\"{t['benchmark']}\\t{t['task_id']}\\tbenchmarks/{t['task_dir']}\")
")

if [ "${#TASK_ROWS[@]}" -eq 0 ]; then
    echo "ERROR: No tasks selected"
    exit 1
fi

declare -A TASK_PATH_BY_ID
declare -A TASK_BENCH_BY_ID
TASK_IDS=()
for row in "${TASK_ROWS[@]}"; do
    bm=$(echo "$row" | cut -f1)
    tid=$(echo "$row" | cut -f2)
    tpath=$(echo "$row" | cut -f3)
    TASK_IDS+=("$tid")
    TASK_PATH_BY_ID["$tid"]="$tpath"
    TASK_BENCH_BY_ID["$tid"]="$bm"
done

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
JOBS_BASE="runs/${CATEGORY}/github_agent_compare_${TIMESTAMP}"
mkdir -p "$JOBS_BASE"

VARIANTS=(
  "copilot_baseline|$COPILOT_AGENT_PATH|$MODEL_COPILOT|none"
  "copilot_github|$COPILOT_AGENT_PATH|$MODEL_COPILOT|$GITHUB_MCP_MODE"
  "codex_baseline|$CODEX_AGENT_PATH|$MODEL_CODEX|none"
  "codex_github|$CODEX_AGENT_PATH|$MODEL_CODEX|$GITHUB_MCP_MODE"
)

echo "=============================================="
echo "GitHub MCP Agent Comparison Scaffold"
echo "=============================================="
echo "Benchmark filter: ${BENCHMARK_FILTER:-<all selected benchmarks>}"
echo "Tasks: ${#TASK_IDS[@]}"
echo "Dry run: $DRY_RUN"
echo "Jobs base: $JOBS_BASE"
echo ""
printf "Variants:\n"
for v in "${VARIANTS[@]}"; do
    IFS='|' read -r name ap model mcp <<< "$v"
    echo "  - $name"
    echo "    agent: $ap"
    echo "    model: $model"
    echo "    mcp:   $mcp"
done
echo ""

if [ "$DRY_RUN" = true ]; then
    for v in "${VARIANTS[@]}"; do
        IFS='|' read -r name ap model mcp <<< "$v"
        echo "[DRY RUN] $name"
        for tid in "${TASK_IDS[@]}"; do
            echo "  BASELINE_MCP_TYPE=$mcp harbor run --path ${TASK_PATH_BY_ID[$tid]} --agent-import-path $ap --model $model --jobs-dir $JOBS_BASE/$name -n $CONCURRENCY --timeout-multiplier $TIMEOUT_MULTIPLIER"
        done
    done
    exit 0
fi

_run_variant_single() {
    local task_id=$1
    local task_home=$2
    local task_path="${TASK_PATH_BY_ID[$task_id]}"
    if [ ! -d "$task_path" ]; then
        echo "WARNING: Task directory missing: $task_path"
        return 1
    fi

    echo "Running [$RUN_VARIANT_NAME] $task_id [HOME=$task_home]"
    BASELINE_MCP_TYPE="$RUN_VARIANT_MCP" harbor run \
        --path "$task_path" \
        --agent-import-path "$RUN_VARIANT_AGENT_PATH" \
        --model "$RUN_VARIANT_MODEL" \
        --jobs-dir "$RUN_VARIANT_JOBS_DIR" \
        -n "$CONCURRENCY" \
        --timeout-multiplier "$TIMEOUT_MULTIPLIER" \
        2>&1 | tee -a "${RUN_VARIANT_JOBS_DIR}.log" \
        || echo "WARNING: failed [$RUN_VARIANT_NAME] $task_id"
}

for v in "${VARIANTS[@]}"; do
    IFS='|' read -r RUN_VARIANT_NAME RUN_VARIANT_AGENT_PATH RUN_VARIANT_MODEL RUN_VARIANT_MCP <<< "$v"
    RUN_VARIANT_JOBS_DIR="$JOBS_BASE/$RUN_VARIANT_NAME"
    mkdir -p "$RUN_VARIANT_JOBS_DIR"

    echo ""
    echo "=============================================="
    echo "Running variant: $RUN_VARIANT_NAME"
    echo "=============================================="
    run_canary_then_batch TASK_IDS _run_variant_single "$RUN_VARIANT_JOBS_DIR" "$RUN_VARIANT_NAME"
done

echo ""
echo "Done. Output in: $JOBS_BASE"
