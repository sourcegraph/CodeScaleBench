#!/bin/bash
# Continuation from step 2 after the `local` bug fix.
# Step 1 (NodeBB baseline) already completed successfully.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

AGENT_DIR="${AGENT_DIR:-$HOME/evals/custom_agents/agents/claudecode}"
export PYTHONPATH="${AGENT_DIR}:$(pwd):$PYTHONPATH"

# Shared config: subscription mode + token refresh
source "$SCRIPT_DIR/_common.sh"

if [ -f ~/evals/.env.local ]; then
    source ~/evals/.env.local
fi


ensure_fresh_token

SELECTION_FILE="$SCRIPT_DIR/selected_benchmark_tasks.json"
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
MODEL="${MODEL:-anthropic/claude-opus-4-6}"
CONCURRENCY=2
TIMEOUT_MULTIPLIER=10

SWEBENCH_HYBRID_DIR="runs/official/swebenchpro_selected_opus_20260202_144222/sourcegraph_full"

NODEBB_TASKS=(
    "instance_nodebb__nodebb-76c6e30282906ac664f2c9278fc90999b27b1f48-vd59a5728dfc977f44533186ace531248c2917516"
    "instance_nodebb__nodebb-eb49a64974ca844bca061744fb3383f5d13b02ad-vnan"
    "instance_nodebb__nodebb-f1a80d48cc45877fcbadf34c2345dd9709722c7f-v4fbcfae8b15e4ce5d132c408bca69ebb9cf146ed"
)

get_swebench_sg_repo() {
    local task_id=$1
    local sg_repo
    sg_repo=$(python3 -c "
import re
tid = '$task_id'
m = re.match(r'(?:instance_)?(.+?)__(.+?)-([a-f0-9]{7,40})', tid)
if m:
    org = m.group(1).replace('__','/')
    repo = m.group(2)
    commit = m.group(3)[:8]
    print(f'{org}--{repo}--{commit}')
" 2>/dev/null)
    if [ -n "$sg_repo" ]; then
        echo "sg-benchmarks/$sg_repo"
    else
        echo ""
    fi
}

echo "=============================================="
echo "Resuming from Step 2"
echo "=============================================="
echo "Start time: $(date)"

# ============================================
# STEP 2: Run 3 NodeBB tasks — sourcegraph_full
# ============================================
echo ""
echo "[2/4] Running 3 NodeBB tasks (sourcegraph_full)..."
echo "  Jobs dir: $SWEBENCH_HYBRID_DIR"
echo ""

for task_id in "${NODEBB_TASKS[@]}"; do
    sg_repo=$(get_swebench_sg_repo "$task_id")
    if [ -n "$sg_repo" ]; then
        export SOURCEGRAPH_REPO_NAME="$sg_repo"
        echo "  [sourcegraph_full] $task_id -> SOURCEGRAPH_REPO_NAME=${sg_repo}"
    else
        unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
        echo "  [sourcegraph_full] $task_id -> no SG repo mapping"
    fi
    BASELINE_MCP_TYPE=sourcegraph_full harbor run \
        --dataset swebenchpro \
        -t "$task_id" \
        --agent-import-path "${AGENT_PATH}" \
        --model "${MODEL}" \
        --jobs-dir "${SWEBENCH_HYBRID_DIR}" \
        -n ${CONCURRENCY} \
        --timeout-multiplier ${TIMEOUT_MULTIPLIER} \
        2>&1 || echo "  WARNING: task failed: $task_id"
done
unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true

echo "[2/4] NodeBB hybrid DONE at $(date)"

# ============================================
# STEP 3: Locobench baseline
# ============================================
echo ""
echo "[3/4] Starting locobench baseline (selected tasks)..."
echo ""

./configs/locobench_3config.sh --baseline-only

echo "[3/4] Locobench baseline DONE at $(date)"

# ============================================
# STEP 4: Locobench sourcegraph_full
# ============================================
echo ""
echo "[4/4] Starting locobench sourcegraph_full (full MCP)..."
echo ""

./configs/locobench_3config.sh --full-only

echo "[4/4] Locobench hybrid DONE at $(date)"

echo ""
echo "=============================================="
echo "All Remaining Runs Complete!"
echo "=============================================="
echo "End time: $(date)"
