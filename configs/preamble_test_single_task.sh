#!/bin/bash
# Preamble Validation Test — Single Task
#
# Tests improved preamble (V3 with deepsearch guidance) on the most representative task.
# Runs: pkg-doc-001 (K8s Docs) with baseline + sourcegraph_full
#
# Usage:
#   ./configs/preamble_test_single_task.sh           # Run both configs
#   ./configs/preamble_test_single_task.sh --baseline-only
#   ./configs/preamble_test_single_task.sh --full-only

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# Agent module lives in the evals repo
AGENT_DIR="${AGENT_DIR:-$HOME/evals/custom_agents/agents/claudecode}"
export PYTHONPATH="${AGENT_DIR}:$(pwd):$PYTHONPATH"

# Shared config
source "$SCRIPT_DIR/_common.sh"

# Load credentials
if [ -f ~/evals/.env.local ]; then
    echo "Loading credentials from ~/evals/.env.local..."
    source ~/evals/.env.local
else
    echo "ERROR: ~/evals/.env.local not found"
    exit 1
fi

# Verify auth mode
enforce_subscription_mode

# Config
MODEL="${MODEL:-anthropic/claude-opus-4-6}"
CATEGORY="${CATEGORY:-preamble_test}"
RUN_BASELINE=false  # Default: only test the preamble (MCP version)
RUN_FULL=true
TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")
RUN_DIR="runs/official/preamble_test_v3_single_${TIMESTAMP}"

# Parse args
while [[ $# -gt 0 ]]; do
    case $1 in
        --with-baseline)
            RUN_BASELINE=true
            shift
            ;;
        --model)
            MODEL="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--with-baseline] [--model MODEL]"
            exit 1
            ;;
    esac
done

# Task selection
TASK_FILE="configs/preamble_test_single.json"
if [ ! -f "$TASK_FILE" ]; then
    echo "ERROR: Task file not found: $TASK_FILE"
    exit 1
fi

TASK_ID=$(python3 -c "import json; print(json.load(open('$TASK_FILE'))['tasks'][0]['task_id'])")
TASK_DIR=$(python3 -c "import json; print(json.load(open('$TASK_FILE'))['tasks'][0]['task_dir'])")

echo "============================================"
echo "Preamble V3 Validation Test — Single Task"
echo "============================================"
echo "Task: $TASK_ID"
echo "Benchmark: K8s Docs"
echo "Model: $MODEL"
echo "Preamble: V3 (balanced deepsearch guidance)"
echo "Run directory: $RUN_DIR"
if [ "$RUN_BASELINE" = true ]; then
    echo "Configs: baseline + sourcegraph_full"
else
    echo "Configs: sourcegraph_full only (use --with-baseline to include baseline)"
fi
echo ""

# Create run directory
mkdir -p "$RUN_DIR"

# For single-task sequential runs, we just need to ensure tokens are fresh
# No need for multi-account setup

# Run baseline
if [ "$RUN_BASELINE" = true ]; then
    echo ""
    echo "=== Running BASELINE (no MCP) ==="
    echo ""

    ensure_fresh_token

    BASELINE_MCP_TYPE=none harbor run \
        --path "benchmarks/$TASK_DIR" \
        --agent-import-path "agents.claude_baseline_agent:BaselineClaudeCodeAgent" \
        --model "$MODEL" \
        --runs-dir "$RUN_DIR/baseline" \
        --timeout-multiplier 10 \
        -n 1
fi

# Run sourcegraph_full (with new preamble)
if [ "$RUN_FULL" = true ]; then
    echo ""
    echo "=== Running SOURCEGRAPH_FULL (new preamble V3) ==="
    echo ""

    ensure_fresh_token

    BASELINE_MCP_TYPE=sourcegraph_full harbor run \
        --path "benchmarks/$TASK_DIR" \
        --agent-import-path "agents.claude_baseline_agent:BaselineClaudeCodeAgent" \
        --model "$MODEL" \
        --runs-dir "$RUN_DIR/sourcegraph_full" \
        --timeout-multiplier 10 \
        -n 1
fi

echo ""
echo "============================================"
echo "Single-task preamble test complete!"
echo "============================================"
echo "Results in: $RUN_DIR"
echo ""
echo "Next steps:"
echo "1. Review MCP tool usage in: $RUN_DIR/sourcegraph_full/*/agent/trajectory.json"
echo "2. Check deepsearch usage and polling success rate"
echo "3. Verify agent follows preamble guidance (sync first, deepsearch when needed)"
echo "4. If validated, expand to 5-task set, then full 14-task set"
echo ""
echo "To include baseline comparison next time: $0 --with-baseline"
echo ""
