#!/bin/bash
# SG-Only Build-Requiring Suites: 2-Config Comparison
#
# Runs build-requiring benchmark tasks across 2 configurations:
#   1. sg_only_env (truncated source — Dockerfile.sg_only swapped in, same agent MCP type)
#   2. sourcegraph_full (full local repo + MCP, for comparison)
#
# These suites require compilation/testing — the verifier runs the project's
# test suite. The agent's setup() hook truncates source files and backs up
# the full repo to /repo_full/. The verifier wrapper restores the full repo
# and overlays agent-written files before running tests.
#
# For SWE-bench Pro: uses pre-built DockerHub images (no custom Dockerfile needed).
#   The agent's setup() hook handles truncation at container start.
# For PyTorch/Enterprise: uses existing Dockerfiles (truncation via setup() hook).
#
# Usage:
#   ./configs/sgonly_build_2config.sh [OPTIONS]
#
# Options:
#   --sgonly-only          Run only sg_only_env config
#   --full-only            Run only sourcegraph_full config
#   --suite SUITE          Run only one suite (swebenchpro|pytorch|enterprise)
#   --model MODEL          Override model (default: claude-opus-4-6)
#   --category CATEGORY    Run category (default: official)
#
# Prerequisites:
#   - ~/evals/.env.local with USE_SUBSCRIPTION=true
#   - SOURCEGRAPH_ACCESS_TOKEN in .env.local
#   - sgonly_verifier_wrapper.sh in each task's tests/ directory (for build tasks)
#   - For SWE-bench Pro: harbor dataset access

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

AGENT_DIR="${AGENT_DIR:-$HOME/evals/custom_agents/agents/claudecode}"
export PYTHONPATH="${AGENT_DIR}:$(pwd):$PYTHONPATH"

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
TIMEOUT_MULTIPLIER=10
RUN_SGONLY=true
RUN_FULL=true
SUITE_FILTER=""
CATEGORY="${CATEGORY:-staging}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --sgonly-only) RUN_FULL=false; shift ;;
        --full-only)   RUN_SGONLY=false; shift ;;
        --suite)       SUITE_FILTER="$2"; shift 2 ;;
        --model)       MODEL="$2"; shift 2 ;;
        --category)    CATEGORY="$2"; shift 2 ;;
        *)             echo "Unknown option: $1"; exit 1 ;;
    esac
done

setup_dual_accounts

# ============================================
# TASK DEFINITIONS
# ============================================
BENCHMARKS_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks"
SELECTION_FILE="$SCRIPT_DIR/selected_benchmark_tasks.json"

# SWE-bench Pro: pilot subset (10 tasks)
readarray -t SWEBENCH_TASKS < <(python3 -c "
import json
tasks = json.load(open('$SELECTION_FILE'))['tasks']
# Pick first 10 SWE-bench Pro tasks for pilot
count = 0
for t in tasks:
    if t['benchmark'] == 'ccb_swebenchpro' and count < 10:
        print(t['task_id'])
        count += 1
")

# PyTorch: pilot subset (5 tasks)
readarray -t PYTORCH_TASKS < <(python3 -c "
import json
tasks = json.load(open('$SELECTION_FILE'))['tasks']
count = 0
for t in tasks:
    if t['benchmark'] == 'ccb_pytorch' and count < 5:
        print(t['task_id'])
        count += 1
")

# Enterprise: all selected tasks
readarray -t ENTERPRISE_TASKS < <(python3 -c "
import json
tasks = json.load(open('$SELECTION_FILE'))['tasks']
for t in tasks:
    if t['benchmark'] == 'ccb_enterprise':
        print(t['task_id'])
")

# SG repo mappings
declare -A SWEBENCH_SG_REPO
while IFS=$'\t' read -r task_id repo; do
    SWEBENCH_SG_REPO["$task_id"]="$repo"
done < <(python3 -c "
import json
tasks = json.load(open('$SELECTION_FILE'))['tasks']
for t in tasks:
    if t['benchmark'] == 'ccb_swebenchpro' and t.get('repo'):
        # SWE-bench Pro repos: use github.com/ prefix
        repo = t['repo']
        if not repo.startswith('github.com/') and not repo.startswith('sg-benchmarks/'):
            repo = 'github.com/' + repo
        print(f\"{t['task_id']}\t{repo}\")
")

declare -A PYTORCH_SG_REPO
while IFS=$'\t' read -r task_id repo; do
    PYTORCH_SG_REPO["$task_id"]="$repo"
done < <(python3 -c "
import json
tasks = json.load(open('$SELECTION_FILE'))['tasks']
for t in tasks:
    if t['benchmark'] == 'ccb_pytorch' and t.get('repo'):
        repo = t['repo']
        if not repo.startswith('github.com/') and not repo.startswith('sg-benchmarks/'):
            repo = 'github.com/' + repo
        print(f\"{t['task_id']}\t{repo}\")
")

declare -A ENTERPRISE_SG_REPO
while IFS=$'\t' read -r task_id repo; do
    ENTERPRISE_SG_REPO["$task_id"]="$repo"
done < <(python3 -c "
import json
tasks = json.load(open('$SELECTION_FILE'))['tasks']
for t in tasks:
    if t['benchmark'] == 'ccb_enterprise' and t.get('repo'):
        repo = t['repo']
        if not repo.startswith('github.com/') and not repo.startswith('sg-benchmarks/'):
            repo = 'github.com/' + repo
        print(f\"{t['task_id']}\t{repo}\")
")

# Derive model short name
_model_lower=$(echo "$MODEL" | awk -F/ '{print $NF}' | tr '[:upper:]' '[:lower:]')
case "$_model_lower" in
    *opus*)   MODEL_SHORT="opus" ;;
    *sonnet*) MODEL_SHORT="sonnet" ;;
    *haiku*)  MODEL_SHORT="haiku" ;;
    *)        MODEL_SHORT=$(echo "$_model_lower" | tr -d '-' | tr -d '_' | cut -c1-8) ;;
esac

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
JOBS_BASE="runs/${CATEGORY}/sgonly_build_${MODEL_SHORT}_${TIMESTAMP}"
mkdir -p "${JOBS_BASE}"

echo "=============================================="
echo "SG-Only Build Suites: 2-Config Comparison"
echo "=============================================="
echo "Model: ${MODEL}"
echo "Suite filter: ${SUITE_FILTER:-all}"
echo "SWE-bench Pro tasks: ${#SWEBENCH_TASKS[@]}"
echo "PyTorch tasks: ${#PYTORCH_TASKS[@]}"
echo "Enterprise tasks: ${#ENTERPRISE_TASKS[@]}"
echo "Run SG-only: ${RUN_SGONLY}"
echo "Run Full: ${RUN_FULL}"
echo "Jobs directory: ${JOBS_BASE}"
echo ""

# ============================================
# HELPERS
# ============================================
inject_verifier_wrapper() {
    # Copy sgonly_verifier_wrapper.sh into a task's tests/ directory
    local task_dir=$1
    local tests_dir="${task_dir}/tests"
    local wrapper_src="${SCRIPT_DIR}/../scripts/sgonly_verifier_wrapper.sh"

    if [ -d "$tests_dir" ] && [ -f "$wrapper_src" ]; then
        cp "$wrapper_src" "${tests_dir}/sgonly_verifier_wrapper.sh"
        chmod +x "${tests_dir}/sgonly_verifier_wrapper.sh"
    fi
}

remove_verifier_wrapper() {
    local task_dir=$1
    rm -f "${task_dir}/tests/sgonly_verifier_wrapper.sh"
}

run_task() {
    local task_id=$1
    local task_dir=$2
    local run_label=$3
    local sg_repo=$4
    local use_dataset=$5  # "swebenchpro" or empty
    local jobs_subdir="${JOBS_BASE}/${run_label}"

    mkdir -p "$jobs_subdir"

    if [ -n "$sg_repo" ]; then
        export SOURCEGRAPH_REPO_NAME="$sg_repo"
    else
        unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
    fi

    echo "  Running ${task_id} [${run_label}] (repo: ${sg_repo:-none})..."

    # Both sg_only_env and sourcegraph_full use the same agent MCP type.
    if [ -n "$use_dataset" ]; then
        BASELINE_MCP_TYPE=sourcegraph_full harbor run \
            --dataset "$use_dataset" \
            -t "$task_id" \
            --agent-import-path "$AGENT_PATH" \
            --model "$MODEL" \
            --jobs-dir "$jobs_subdir" \
            -n $CONCURRENCY \
            --timeout-multiplier $TIMEOUT_MULTIPLIER \
            2>&1 | tee "${jobs_subdir}/${task_id}.log" \
            || echo "  WARNING: ${task_id} [${run_label}] returned non-zero"
    else
        BASELINE_MCP_TYPE=sourcegraph_full harbor run \
            --path "$task_dir" \
            --agent-import-path "$AGENT_PATH" \
            --model "$MODEL" \
            --jobs-dir "$jobs_subdir" \
            -n $CONCURRENCY \
            --timeout-multiplier $TIMEOUT_MULTIPLIER \
            2>&1 | tee "${jobs_subdir}/${task_id}.log" \
            || echo "  WARNING: ${task_id} [${run_label}] returned non-zero"
    fi
}

# ============================================
# RUN SG-ONLY CONFIG
# ============================================
if [ "$RUN_SGONLY" = true ]; then
    ensure_fresh_token_all

    # SWE-bench Pro (uses harbor dataset — setup() hook handles truncation)
    if [ -z "$SUITE_FILTER" ] || [ "$SUITE_FILTER" = "swebenchpro" ]; then
        echo ""
        echo "[SWE-bench Pro SG-ONLY] Running ${#SWEBENCH_TASKS[@]} tasks..."
        for task_id in "${SWEBENCH_TASKS[@]}"; do
            sg_repo="${SWEBENCH_SG_REPO[$task_id]:-}"
            run_task "$task_id" "" "sg_only_env" "$sg_repo" "swebenchpro"
        done
    fi

    # PyTorch (uses --path, setup() hook handles truncation)
    if [ -z "$SUITE_FILTER" ] || [ "$SUITE_FILTER" = "pytorch" ]; then
        echo ""
        echo "[PyTorch SG-ONLY] Running ${#PYTORCH_TASKS[@]} tasks..."
        for task_id in "${PYTORCH_TASKS[@]}"; do
            task_dir="${BENCHMARKS_DIR}/ccb_pytorch/${task_id}"
            sg_repo="${PYTORCH_SG_REPO[$task_id]:-}"
            inject_verifier_wrapper "$task_dir"
            run_task "$task_id" "$task_dir" "sg_only_env" "$sg_repo" ""
            remove_verifier_wrapper "$task_dir"
        done
    fi

    # Enterprise (uses --path, setup() hook handles truncation)
    if [ -z "$SUITE_FILTER" ] || [ "$SUITE_FILTER" = "enterprise" ]; then
        echo ""
        echo "[Enterprise SG-ONLY] Running ${#ENTERPRISE_TASKS[@]} tasks..."
        for task_id in "${ENTERPRISE_TASKS[@]}"; do
            task_dir="${BENCHMARKS_DIR}/ccb_enterprise/${task_id}"
            sg_repo="${ENTERPRISE_SG_REPO[$task_id]:-}"
            inject_verifier_wrapper "$task_dir"
            run_task "$task_id" "$task_dir" "sg_only_env" "$sg_repo" ""
            remove_verifier_wrapper "$task_dir"
        done
    fi
fi

# ============================================
# RUN FULL CONFIG (comparison)
# ============================================
if [ "$RUN_FULL" = true ]; then
    ensure_fresh_token_all

    if [ -z "$SUITE_FILTER" ] || [ "$SUITE_FILTER" = "swebenchpro" ]; then
        echo ""
        echo "[SWE-bench Pro FULL] Running ${#SWEBENCH_TASKS[@]} tasks..."
        for task_id in "${SWEBENCH_TASKS[@]}"; do
            sg_repo="${SWEBENCH_SG_REPO[$task_id]:-}"
            run_task "$task_id" "" "sourcegraph_full" "$sg_repo" "swebenchpro"
        done
    fi

    if [ -z "$SUITE_FILTER" ] || [ "$SUITE_FILTER" = "pytorch" ]; then
        echo ""
        echo "[PyTorch FULL] Running ${#PYTORCH_TASKS[@]} tasks..."
        for task_id in "${PYTORCH_TASKS[@]}"; do
            task_dir="${BENCHMARKS_DIR}/ccb_pytorch/${task_id}"
            sg_repo="${PYTORCH_SG_REPO[$task_id]:-}"
            run_task "$task_id" "$task_dir" "sourcegraph_full" "$sg_repo" ""
        done
    fi

    if [ -z "$SUITE_FILTER" ] || [ "$SUITE_FILTER" = "enterprise" ]; then
        echo ""
        echo "[Enterprise FULL] Running ${#ENTERPRISE_TASKS[@]} tasks..."
        for task_id in "${ENTERPRISE_TASKS[@]}"; do
            task_dir="${BENCHMARKS_DIR}/ccb_enterprise/${task_id}"
            sg_repo="${ENTERPRISE_SG_REPO[$task_id]:-}"
            run_task "$task_id" "$task_dir" "sourcegraph_full" "$sg_repo" ""
        done
    fi
fi

echo ""
echo "=============================================="
echo "SG-Only Build Comparison Complete!"
echo "=============================================="
echo "Results saved to: ${JOBS_BASE}"
echo ""
echo "Analyze with:"
echo "  python3 scripts/generate_manifest.py"
echo "  python3 scripts/aggregate_status.py --format table"
