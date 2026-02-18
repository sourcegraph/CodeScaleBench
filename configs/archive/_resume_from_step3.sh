#!/bin/bash
# Continuation: run locobench baseline + sourcegraph_full.
# Steps 1-2 (NodeBB baseline + hybrid) already completed.
# Uses --task-name "*" for baseline (individual task names cause verifier issues).
# Uses per-task iteration for MCP mode (needed for SOURCEGRAPH_REPO_NAME).
# Pipeline filters to selected 25 tasks at report time.

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

echo "=============================================="
echo "Locobench Runs (baseline + sourcegraph_full)"
echo "=============================================="
echo "Start time: $(date)"

# ============================================
# STEP 3: Locobench baseline (all tasks, filter at report time)
# ============================================
echo ""
echo "[3/4] Starting locobench baseline..."
echo ""

./configs/locobench_3config.sh --baseline-only

echo "[3/4] Locobench baseline DONE at $(date)"

# ============================================
# STEP 4: Locobench sourcegraph_full (full MCP)
# ============================================
echo ""
echo "[4/4] Starting locobench sourcegraph_full (full MCP)..."
echo ""

./configs/locobench_3config.sh --full-only

echo "[4/4] Locobench hybrid DONE at $(date)"

echo ""
echo "=============================================="
echo "All Locobench Runs Complete!"
echo "=============================================="
echo "End time: $(date)"
echo ""
echo "Next steps:"
echo "  1. Move old 50-task runs to archive:"
echo "     mv runs/official/locobench_50_tasks_opus_20260202_* runs/official/archive/"
echo "  2. Regenerate report:"
echo "     python3 scripts/generate_eval_report.py --runs-dir runs/official/ --output-dir ./eval_reports/"
