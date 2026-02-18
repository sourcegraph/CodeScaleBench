#!/bin/bash
# LargeRepo SG_base Comparison: kubernetes--latest vs kubernetes--latest--precise
#
# Runs big-code-k8s-001 twice with sg_base config, once per Sourcegraph mirror,
# to compare standard vs precise (scip-go) code intelligence indexing.
#
# Output dirs:
#   runs/official/bigcode_sgcompare_opus_TIMESTAMP/
#     sourcegraph_base_latest/       (kubernetes--latest)
#     sourcegraph_base_precise/      (kubernetes--latest--precise)
#
# Usage:
#   ./configs/largerepo_sg_compare.sh [options]
#
# Options:
#   --model MODEL    Override model (default: anthropic/claude-opus-4-6)
#   --category CAT   Override run category (default: official)
#   --latest-only    Run only the --latest mirror
#   --precise-only   Run only the --latest--precise mirror

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# Agent module
AGENT_DIR="${AGENT_DIR:-$HOME/evals/custom_agents/agents/claudecode}"
export PYTHONPATH="${AGENT_DIR}:$(pwd):$PYTHONPATH"

# Shared config: subscription mode + token refresh
source "$SCRIPT_DIR/_common.sh"

# ============================================
# LOAD CREDENTIALS
# ============================================
if [ -f ~/evals/.env.local ]; then
    echo "Loading credentials from ~/evals/.env.local..."
    source ~/evals/.env.local
else
    echo "Warning: ~/evals/.env.local not found"
fi

enforce_subscription_mode
if [ -n "$SOURCEGRAPH_ACCESS_TOKEN" ]; then
    echo "SOURCEGRAPH_ACCESS_TOKEN: set (${#SOURCEGRAPH_ACCESS_TOKEN} chars)"
else
    echo "ERROR: SOURCEGRAPH_ACCESS_TOKEN not set — required for sg_base runs"
    exit 1
fi
echo ""

ensure_fresh_token

# ============================================
# CONFIGURATION
# ============================================
TASK_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks/ccb_largerepo/big-code-k8s-001"
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
MODEL="${MODEL:-anthropic/claude-opus-4-6}"
CONCURRENCY=1
TIMEOUT_MULTIPLIER=10
CATEGORY="${CATEGORY:-staging}"
RUN_LATEST=true
RUN_PRECISE=true

# The two mirrors to compare
SG_REPO_LATEST="sg-benchmarks/kubernetes--latest"
SG_REPO_PRECISE="sg-benchmarks/kubernetes--latest--precise"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --model)
            MODEL="$2"
            shift 2
            ;;
        --category)
            CATEGORY="$2"
            shift 2
            ;;
        --latest-only)
            RUN_PRECISE=false
            shift
            ;;
        --precise-only)
            RUN_LATEST=false
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Set up dual-account support
setup_dual_accounts

# Verify task exists
if [ ! -d "$TASK_DIR" ]; then
    echo "ERROR: Task directory not found: $TASK_DIR"
    exit 1
fi

# Derive model short name
_model_lower=$(echo "$MODEL" | awk -F/ '{print $NF}' | tr '[:upper:]' '[:lower:]')
case "$_model_lower" in
    *opus*)   MODEL_SHORT="opus" ;;
    *sonnet*) MODEL_SHORT="sonnet" ;;
    *haiku*)  MODEL_SHORT="haiku" ;;
    *)        MODEL_SHORT=$(echo "$_model_lower" | tr -d '-' | tr -d '_' | cut -c1-8) ;;
esac

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
JOBS_BASE="runs/${CATEGORY}/bigcode_sgcompare_${MODEL_SHORT}_${TIMESTAMP}"

echo "========================================"
echo "LargeRepo SG Compare: latest vs precise"
echo "========================================"
echo "  Task:     big-code-k8s-001"
echo "  Model:    $MODEL"
echo "  Mirror A: $SG_REPO_LATEST"
echo "  Mirror B: $SG_REPO_PRECISE"
echo "  Output:   $JOBS_BASE/"
echo "  Timeout:  ${TIMEOUT_MULTIPLIER}x"
echo ""

# ============================================
# RUN: kubernetes--latest (standard indexing)
# ============================================
if [ "$RUN_LATEST" = true ]; then
    SUBDIR="${JOBS_BASE}/sourcegraph_base_latest"
    mkdir -p "$SUBDIR"

    echo ""
    echo "========================================"
    echo "Run 1/2: sg_base with kubernetes--latest"
    echo "========================================"

    ensure_fresh_token_all

    export SOURCEGRAPH_REPO_NAME="$SG_REPO_LATEST"
    BASELINE_MCP_TYPE=sourcegraph_base harbor run \
        --path "$TASK_DIR" \
        --agent-import-path "$AGENT_PATH" \
        --model "$MODEL" \
        --jobs-dir "$SUBDIR" \
        -n $CONCURRENCY \
        --timeout-multiplier $TIMEOUT_MULTIPLIER \
        2>&1 | tee "${SUBDIR}/big-code-k8s-001.log" \
        || echo "WARNING: latest run failed (exit code: $?)"

    echo ""
    echo "Run 1/2 complete. Results in: $SUBDIR"
fi

# ============================================
# RUN: kubernetes--latest--precise (scip-go)
# ============================================
if [ "$RUN_PRECISE" = true ]; then
    SUBDIR="${JOBS_BASE}/sourcegraph_base_precise"
    mkdir -p "$SUBDIR"

    echo ""
    echo "========================================"
    echo "Run 2/2: sg_base with kubernetes--latest--precise"
    echo "========================================"

    ensure_fresh_token_all

    export SOURCEGRAPH_REPO_NAME="$SG_REPO_PRECISE"
    BASELINE_MCP_TYPE=sourcegraph_base harbor run \
        --path "$TASK_DIR" \
        --agent-import-path "$AGENT_PATH" \
        --model "$MODEL" \
        --jobs-dir "$SUBDIR" \
        -n $CONCURRENCY \
        --timeout-multiplier $TIMEOUT_MULTIPLIER \
        2>&1 | tee "${SUBDIR}/big-code-k8s-001.log" \
        || echo "WARNING: precise run failed (exit code: $?)"

    echo ""
    echo "Run 2/2 complete. Results in: $SUBDIR"
fi

# ============================================
# SUMMARY
# ============================================
echo ""
echo "========================================"
echo "SG COMPARE COMPLETE"
echo "========================================"
echo "Output: $JOBS_BASE/"
echo ""

# Show results if available
for subdir in "${JOBS_BASE}/sourcegraph_base_latest" "${JOBS_BASE}/sourcegraph_base_precise"; do
    if [ -d "$subdir" ]; then
        label=$(basename "$subdir")
        result_file=$(find "$subdir" -name "result.json" -path "*/big-code-k8s*" 2>/dev/null | head -1)
        if [ -n "$result_file" ]; then
            reward=$(python3 -c "import json; r=json.load(open('$result_file')); print(r.get('rewards',{}).get('reward', r.get('rewards',{}).get('score','N/A')))" 2>/dev/null || echo "N/A")
            echo "  $label: reward=$reward"
        else
            echo "  $label: no result.json found"
        fi
    fi
done
echo ""
echo "Compare with: diff <(jq . $JOBS_BASE/sourcegraph_base_latest/*/result.json) <(jq . $JOBS_BASE/sourcegraph_base_precise/*/result.json)"
