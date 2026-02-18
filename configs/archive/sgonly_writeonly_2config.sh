#!/bin/bash
# SG-Only Write-Only Suites: 2-Config Comparison
#
# Runs write-only benchmark tasks (K8s Docs, LinuxFLBench, Investigation)
# across 2 configurations:
#   1. sg_only_env (no local source — Dockerfile.sg_only swapped in, same agent MCP type)
#   2. sourcegraph_full (full local repo + MCP, for comparison)
#
# These suites are "write-only" — the verifier checks agent OUTPUT
# (doc.go, JSON answer, investigation report), NOT compiled/tested code.
# So no /repo_full/ backup is needed.
#
# Usage:
#   ./configs/sgonly_writeonly_2config.sh [OPTIONS]
#
# Options:
#   --sgonly-only          Run only sg_only_env config
#   --full-only            Run only sourcegraph_full config
#   --suite SUITE          Run only one suite (k8sdocs|linuxflbench|investigation)
#   --model MODEL          Override model (default: claude-opus-4-6)
#   --category CATEGORY    Run category (default: official)
#
# Prerequisites:
#   - ~/evals/.env.local with USE_SUBSCRIPTION=true
#   - SOURCEGRAPH_ACCESS_TOKEN in .env.local
#   - Dockerfile.sg_only present in each task's environment/ dir

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# Agent module lives in the evals repo; add it to PYTHONPATH
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

# Verify auth mode (subscription-only)
enforce_subscription_mode
if [ -n "$SOURCEGRAPH_ACCESS_TOKEN" ]; then
    echo "SOURCEGRAPH_ACCESS_TOKEN: set (${#SOURCEGRAPH_ACCESS_TOKEN} chars)"
else
    echo "ERROR: SOURCEGRAPH_ACCESS_TOKEN required"
    exit 1
fi
echo ""

ensure_fresh_token_all

# ============================================
# CONFIGURATION
# ============================================
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
MODEL="${MODEL:-anthropic/claude-opus-4-6}"
CONCURRENCY=2
TIMEOUT_MULTIPLIER=3
RUN_SGONLY=true
RUN_FULL=true
SUITE_FILTER=""
CATEGORY="${CATEGORY:-staging}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --sgonly-only)
            RUN_FULL=false
            shift
            ;;
        --full-only)
            RUN_SGONLY=false
            shift
            ;;
        --suite)
            SUITE_FILTER="$2"
            shift 2
            ;;
        --model)
            MODEL="$2"
            shift 2
            ;;
        --category)
            CATEGORY="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Set up dual-account support
setup_dual_accounts

# ============================================
# TASK DEFINITIONS
# ============================================
BENCHMARKS_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks"
SELECTION_FILE="$SCRIPT_DIR/selected_benchmark_tasks.json"

# Load selected tasks per suite
readarray -t K8SDOCS_TASKS < <(python3 -c "
import json
tasks = json.load(open('$SELECTION_FILE'))['tasks']
for t in tasks:
    if t['benchmark'] == 'ccb_k8sdocs':
        print(t['task_id'])
")

readarray -t LFL_TASKS < <(python3 -c "
import json
tasks = json.load(open('$SELECTION_FILE'))['tasks']
for t in tasks:
    if t['benchmark'] == 'ccb_linuxflbench':
        print(t['task_id'])
")

readarray -t INV_TASKS < <(python3 -c "
import json
tasks = json.load(open('$SELECTION_FILE'))['tasks']
for t in tasks:
    if t['benchmark'] == 'ccb_investigation':
        print(t['task_id'])
")

# SG repo mappings
declare -A K8SDOCS_SG_REPO=(
    ["apiserver-doc-001"]="github.com/sg-benchmarks/kubernetes--stripped"
    ["applyconfig-doc-001"]="github.com/sg-benchmarks/kubernetes--stripped"
    ["client-go-doc-001"]="github.com/sg-benchmarks/kubernetes--stripped"
    ["fairqueuing-doc-001"]="github.com/sg-benchmarks/kubernetes--stripped"
    ["pkg-doc-001"]="github.com/sg-benchmarks/kubernetes--stripped"
)

declare -A LFL_SG_REPO=(
    ["lfl-acpi-207835"]="github.com/sg-benchmarks/linux--55b2af1c"
    ["lfl-wifi-206661"]="github.com/sg-benchmarks/linux--11a48a5a"
    ["lfl-nfs-117651"]="github.com/sg-benchmarks/linux--07cc49f6"
    ["lfl-sata-203475"]="github.com/sg-benchmarks/linux--fa5941f4"
    ["lfl-sound-53441"]="github.com/sg-benchmarks/linux--07c4ee00"
)

declare -A INV_SG_REPO=(
    ["inv-debug-001"]="github.com/prometheus/prometheus"
    ["inv-impact-001"]="github.com/kubernetes/kubernetes"
    ["inv-migration-001"]="github.com/django/django"
    ["inv-regression-001"]="github.com/grafana/grafana"
)

# Derive short model name
_model_lower=$(echo "$MODEL" | awk -F/ '{print $NF}' | tr '[:upper:]' '[:lower:]')
case "$_model_lower" in
    *opus*)   MODEL_SHORT="opus" ;;
    *sonnet*) MODEL_SHORT="sonnet" ;;
    *haiku*)  MODEL_SHORT="haiku" ;;
    *)        MODEL_SHORT=$(echo "$_model_lower" | tr -d '-' | tr -d '_' | cut -c1-8) ;;
esac

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
JOBS_BASE="runs/${CATEGORY}/sgonly_writeonly_${MODEL_SHORT}_${TIMESTAMP}"
mkdir -p "${JOBS_BASE}"

echo "=============================================="
echo "SG-Only Write-Only Suites: 2-Config Comparison"
echo "=============================================="
echo "Model: ${MODEL}"
echo "Suite filter: ${SUITE_FILTER:-all}"
echo "K8s Docs tasks: ${#K8SDOCS_TASKS[@]}"
echo "LinuxFLBench tasks: ${#LFL_TASKS[@]}"
echo "Investigation tasks: ${#INV_TASKS[@]}"
echo "Run SG-only: ${RUN_SGONLY}"
echo "Run Full: ${RUN_FULL}"
echo "Jobs directory: ${JOBS_BASE}"
echo ""

# ============================================
# HELPERS
# ============================================
swap_to_sgonly() {
    local task_dir=$1
    local dockerfile="${task_dir}/environment/Dockerfile"
    local sgonly="${task_dir}/environment/Dockerfile.sg_only"
    local backup="${task_dir}/environment/Dockerfile.original"

    if [ ! -f "$sgonly" ]; then
        echo "WARNING: No Dockerfile.sg_only for $(basename $task_dir), skipping"
        return 1
    fi

    cp "$dockerfile" "$backup"
    cp "$sgonly" "$dockerfile"
    return 0
}

restore_dockerfile() {
    local task_dir=$1
    local dockerfile="${task_dir}/environment/Dockerfile"
    local backup="${task_dir}/environment/Dockerfile.original"

    if [ -f "$backup" ]; then
        mv "$backup" "$dockerfile"
    fi
}

run_single_task() {
    local task_id=$1
    local task_dir=$2
    local run_label=$3
    local sg_repo=$4
    local suite_prefix=$5
    local jobs_subdir="${JOBS_BASE}/${run_label}"

    mkdir -p "$jobs_subdir"

    if [ -n "$sg_repo" ]; then
        export SOURCEGRAPH_REPO_NAME="$sg_repo"
    else
        unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
    fi

    echo "  Running ${task_id} [${run_label}] (repo: ${sg_repo:-none})..."

    # sg_only_env is purely an environment change (Dockerfile swap);
    # the agent always runs as sourcegraph_full.
    BASELINE_MCP_TYPE=sourcegraph_full harbor run \
        --path "$task_dir" \
        --agent-import-path "$AGENT_PATH" \
        --model "$MODEL" \
        --jobs-dir "$jobs_subdir" \
        -n $CONCURRENCY \
        --timeout-multiplier $TIMEOUT_MULTIPLIER \
        2>&1 | tee "${jobs_subdir}/${task_id}.log" \
        || echo "  WARNING: ${task_id} [${run_label}] returned non-zero"
}

run_suite() {
    local suite_name=$1
    local suite_dir=$2
    local mcp_type=$3
    shift 3
    local -n task_ids_ref=$1
    shift
    local -n repo_map_ref=$1

    echo ""
    echo "[${suite_name}] Running ${#task_ids_ref[@]} tasks with ${mcp_type}..."

    for task_id in "${task_ids_ref[@]}"; do
        local task_dir="${suite_dir}/${task_id}"
        local sg_repo="${repo_map_ref[$task_id]:-}"
        run_single_task "$task_id" "$task_dir" "$mcp_type" "$sg_repo" "$suite_name"
    done
}

# ============================================
# RUN SG-ONLY CONFIG
# ============================================
if [ "$RUN_SGONLY" = true ]; then
    ensure_fresh_token_all

    # Swap Dockerfiles to sg_only versions
    echo "[SG-ONLY] Swapping Dockerfiles to sg_only versions..."
    SWAP_TASKS=()

    if [ -z "$SUITE_FILTER" ] || [ "$SUITE_FILTER" = "k8sdocs" ]; then
        for task_id in "${K8SDOCS_TASKS[@]}"; do
            task_dir="${BENCHMARKS_DIR}/ccb_k8sdocs/${task_id}"
            if swap_to_sgonly "$task_dir"; then
                SWAP_TASKS+=("k8sdocs:${task_id}")
            fi
        done
    fi

    if [ -z "$SUITE_FILTER" ] || [ "$SUITE_FILTER" = "linuxflbench" ]; then
        for task_id in "${LFL_TASKS[@]}"; do
            task_dir="${BENCHMARKS_DIR}/ccb_linuxflbench/${task_id}"
            if swap_to_sgonly "$task_dir"; then
                SWAP_TASKS+=("lfl:${task_id}")
            fi
        done
    fi

    if [ -z "$SUITE_FILTER" ] || [ "$SUITE_FILTER" = "investigation" ]; then
        for task_id in "${INV_TASKS[@]}"; do
            task_dir="${BENCHMARKS_DIR}/ccb_investigation/${task_id}"
            if swap_to_sgonly "$task_dir"; then
                SWAP_TASKS+=("inv:${task_id}")
            fi
        done
    fi

    echo "  Swapped ${#SWAP_TASKS[@]} Dockerfiles"
    echo ""

    # Run tasks
    if [ -z "$SUITE_FILTER" ] || [ "$SUITE_FILTER" = "k8sdocs" ]; then
        run_suite "K8s Docs" "${BENCHMARKS_DIR}/ccb_k8sdocs" "sg_only_env" K8SDOCS_TASKS K8SDOCS_SG_REPO
    fi
    if [ -z "$SUITE_FILTER" ] || [ "$SUITE_FILTER" = "linuxflbench" ]; then
        run_suite "LinuxFLBench" "${BENCHMARKS_DIR}/ccb_linuxflbench" "sg_only_env" LFL_TASKS LFL_SG_REPO
    fi
    if [ -z "$SUITE_FILTER" ] || [ "$SUITE_FILTER" = "investigation" ]; then
        run_suite "Investigation" "${BENCHMARKS_DIR}/ccb_investigation" "sg_only_env" INV_TASKS INV_SG_REPO
    fi

    # Restore all Dockerfiles
    echo ""
    echo "[SG-ONLY] Restoring original Dockerfiles..."
    if [ -z "$SUITE_FILTER" ] || [ "$SUITE_FILTER" = "k8sdocs" ]; then
        for task_id in "${K8SDOCS_TASKS[@]}"; do
            restore_dockerfile "${BENCHMARKS_DIR}/ccb_k8sdocs/${task_id}"
        done
    fi
    if [ -z "$SUITE_FILTER" ] || [ "$SUITE_FILTER" = "linuxflbench" ]; then
        for task_id in "${LFL_TASKS[@]}"; do
            restore_dockerfile "${BENCHMARKS_DIR}/ccb_linuxflbench/${task_id}"
        done
    fi
    if [ -z "$SUITE_FILTER" ] || [ "$SUITE_FILTER" = "investigation" ]; then
        for task_id in "${INV_TASKS[@]}"; do
            restore_dockerfile "${BENCHMARKS_DIR}/ccb_investigation/${task_id}"
        done
    fi
fi

# ============================================
# RUN FULL CONFIG (comparison)
# ============================================
if [ "$RUN_FULL" = true ]; then
    ensure_fresh_token_all
    echo ""
    echo "[FULL] Running sourcegraph_full comparison..."

    if [ -z "$SUITE_FILTER" ] || [ "$SUITE_FILTER" = "k8sdocs" ]; then
        run_suite "K8s Docs" "${BENCHMARKS_DIR}/ccb_k8sdocs" "sourcegraph_full" K8SDOCS_TASKS K8SDOCS_SG_REPO
    fi
    if [ -z "$SUITE_FILTER" ] || [ "$SUITE_FILTER" = "linuxflbench" ]; then
        run_suite "LinuxFLBench" "${BENCHMARKS_DIR}/ccb_linuxflbench" "sourcegraph_full" LFL_TASKS LFL_SG_REPO
    fi
    if [ -z "$SUITE_FILTER" ] || [ "$SUITE_FILTER" = "investigation" ]; then
        run_suite "Investigation" "${BENCHMARKS_DIR}/ccb_investigation" "sourcegraph_full" INV_TASKS INV_SG_REPO
    fi
fi

echo ""
echo "=============================================="
echo "SG-Only Write-Only Comparison Complete!"
echo "=============================================="
echo "Results saved to: ${JOBS_BASE}"
echo ""
echo "Analyze with:"
echo "  python3 scripts/generate_manifest.py"
echo "  python3 scripts/aggregate_status.py --format table"
