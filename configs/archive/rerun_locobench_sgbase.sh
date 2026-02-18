#!/bin/bash
# Rerun 5 missing LoCoBench SG_base tasks
#
# These tasks hit H3 bug in Feb 3 run, got zero-token auth failures in Feb 9 gapfill,
# and were accidentally omitted from Feb 10 gapfill.

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
ensure_fresh_token

# Use account1 only
SKIP_ACCOUNTS="account2 account3"
setup_dual_accounts

TASKS_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks/ccb_locobench/tasks"
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
MODEL="${MODEL:-anthropic/claude-opus-4-6}"
CONCURRENCY=2
TIMEOUT_MULTIPLIER=10

# The 5 missing tasks
TASK_IDS=(
    "csharp_data_warehouse_expert_012_architectural_understanding_expert_01"
    "csharp_data_warehouse_expert_012_bug_investigation_expert_01"
    "python_data_streaming_expert_085_architectural_understanding_expert_01"
    "python_desktop_development_expert_021_architectural_understanding_expert_01"
    "rust_api_microservice_expert_008_architectural_understanding_expert_01"
)

MODEL_SHORT="opus"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
JOBS_BASE="runs/official/locobench_gapfill_${MODEL_SHORT}_${TIMESTAMP}"
JOBS_DIR="${JOBS_BASE}/sourcegraph_base"
mkdir -p "$JOBS_DIR"

echo "=============================================="
echo "LoCoBench SG_base Gapfill Rerun"
echo "=============================================="
echo "Tasks: ${#TASK_IDS[@]}"
echo "Config: sourcegraph_base"
echo "Output: ${JOBS_DIR}"
echo ""

# Resolve SOURCEGRAPH_REPO_NAME per task
get_sg_repo_name() {
    local task_dir=$1
    local dc_file="${task_dir}/environment/docker-compose.yaml"
    if [ -f "$dc_file" ]; then
        local proj_id=$(grep 'LOCOBENCH_PROJECT_ID=' "$dc_file" | head -1 | sed 's/.*LOCOBENCH_PROJECT_ID=//')
        if [ -n "$proj_id" ]; then
            echo "sg-benchmarks/locobench-${proj_id}"
            return
        fi
    fi
    echo ""
}

_locobench_sgbase_run_single() {
    local task_id=$1
    local task_home=$2
    local task_path="${TASKS_DIR}/${task_id}"
    local sg_repo=$(get_sg_repo_name "$task_path")
    if [ -n "$sg_repo" ]; then
        export SOURCEGRAPH_REPO_NAME="$sg_repo"
        echo "  [sourcegraph_base] Task ${task_id} -> SOURCEGRAPH_REPO_NAME=${sg_repo} [HOME=$task_home]"
    else
        unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
        echo "  [sourcegraph_base] Task ${task_id} -> no SG repo mapping [HOME=$task_home]"
    fi
    BASELINE_MCP_TYPE=sourcegraph_base harbor run \
        --path "$task_path" \
        --agent-import-path "$AGENT_PATH" \
        --model "$MODEL" \
        --jobs-dir "$JOBS_DIR" \
        -n $CONCURRENCY \
        --timeout-multiplier $TIMEOUT_MULTIPLIER \
        --force-build \
        2>&1 | tee "${JOBS_DIR}/${task_id}.log" || true
}

run_canary_then_batch TASK_IDS _locobench_sgbase_run_single "$JOBS_DIR" "sourcegraph_base"

echo ""
echo "=============================================="
echo "Gapfill Complete!"
echo "=============================================="
echo "Results: ${JOBS_DIR}"
echo ""
echo "Verify:"
echo "  python3 scripts/generate_manifest.py"
