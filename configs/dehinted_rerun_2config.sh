#!/bin/bash
# Targeted rerun of 9 de-hinted enterprise/governance tasks
#
# Runs only the 9 tasks redesigned in US-001..US-003 (de-hinted instructions)
# across 2 configurations: baseline + SG_full (paired execution).
#
# Creates separate run dirs for enterprise and governance tasks so MANIFEST
# and IR analysis scripts can detect suite from the dir prefix.
#
# Usage:
#   ./configs/dehinted_rerun_2config.sh [OPTIONS]
#
# Options:
#   --baseline-only   Run only baseline (no MCP)
#   --full-only       Run only MCP-Full (sourcegraph_full)
#   --parallel N      Override parallel job count (default: auto)

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
    echo ""
fi

enforce_subscription_mode
if [ -n "$SOURCEGRAPH_ACCESS_TOKEN" ]; then
    echo "SOURCEGRAPH_ACCESS_TOKEN: set (${#SOURCEGRAPH_ACCESS_TOKEN} chars)"
else
    echo "SOURCEGRAPH_ACCESS_TOKEN: not set"
fi
echo ""

ensure_fresh_token

# ============================================
# CONFIGURATION
# ============================================
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
MODEL="${MODEL:-anthropic/claude-opus-4-6}"
CONCURRENCY=2
TIMEOUT_MULTIPLIER=10
RUN_BASELINE=true
RUN_FULL=true
CATEGORY="${CATEGORY:-official}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --baseline-only)
            RUN_FULL=false
            shift
            ;;
        --full-only)
            RUN_BASELINE=false
            shift
            ;;
        --parallel)
            PARALLEL_JOBS="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

setup_dual_accounts

# ============================================
# TASK DEFINITIONS
# ============================================
ENT_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks/ccb_enterprise"
GOV_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks/ccb_governance"
SELECTION_FILE="$SCRIPT_DIR/selected_benchmark_tasks.json"

# Enterprise de-hinted tasks (6)
ENT_TASK_IDS=(
    "dep-discovery-001"
    "dep-refactor-001"
    "dep-refactor-002"
    "polyglot-ecosystem-001"
    "multi-team-ownership-002"
    "dep-impact-001"
)

# Governance de-hinted tasks (3)
GOV_TASK_IDS=(
    "degraded-context-001"
    "repo-scoped-access-002"
    "policy-enforcement-001"
)

# Sourcegraph repo name mapping
declare -A TASK_SG_REPO_NAMES=(
    ["dep-discovery-001"]="github.com/flipt-io/flipt"
    ["dep-refactor-001"]="github.com/flipt-io/flipt"
    ["dep-refactor-002"]="github.com/flipt-io/flipt"
    ["polyglot-ecosystem-001"]="github.com/flipt-io/flipt"
    ["multi-team-ownership-002"]="github.com/flipt-io/flipt"
    ["dep-impact-001"]="github.com/django/django"
    ["degraded-context-001"]="github.com/flipt-io/flipt"
    ["repo-scoped-access-002"]="github.com/flipt-io/flipt"
    ["policy-enforcement-001"]="github.com/django/django"
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
ENT_JOBS_BASE="runs/${CATEGORY}/enterprise_${MODEL_SHORT}_${TIMESTAMP}"
GOV_JOBS_BASE="runs/${CATEGORY}/governance_${MODEL_SHORT}_${TIMESTAMP}"

echo "=============================================="
echo "De-hinted 9-Task Rerun (2 Configs)"
echo "=============================================="
echo "Model: ${MODEL}"
echo "Enterprise tasks: ${#ENT_TASK_IDS[@]} -> ${ENT_JOBS_BASE}"
echo "Governance tasks: ${#GOV_TASK_IDS[@]} -> ${GOV_JOBS_BASE}"
echo "Parallel jobs: ${PARALLEL_JOBS}"
echo "Run baseline: ${RUN_BASELINE}"
echo "Run MCP-Full: ${RUN_FULL}"
echo ""

mkdir -p "${ENT_JOBS_BASE}" "${GOV_JOBS_BASE}"

# ============================================
# PER-TASK RUN FUNCTIONS
# ============================================
_enterprise_run_single() {
    local task_id=$1
    local task_home=$2
    local config=${3:-baseline}
    local mcp_type=${4:-none}
    local jobs_base=${5:-$ENT_JOBS_BASE}
    local jobs_subdir="${jobs_base}/${config}"
    local task_path="${ENT_DIR}/${task_id}"

    mkdir -p "$jobs_subdir"

    if [ ! -d "$task_path" ]; then
        echo "ERROR: Task directory not found: $task_path"
        return 1
    fi

    echo "Running task: $task_id ($config) [HOME=$task_home]"

    local sg_repo="${TASK_SG_REPO_NAMES[$task_id]:-}"
    if [ -n "$sg_repo" ]; then
        export SOURCEGRAPH_REPO_NAME="$sg_repo"
    else
        unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
    fi

    BASELINE_MCP_TYPE=$mcp_type harbor run \
        --path "$task_path" \
        --agent-import-path "$AGENT_PATH" \
        --model "$MODEL" \
        --jobs-dir "$jobs_subdir" \
        -n $CONCURRENCY \
        --timeout-multiplier $TIMEOUT_MULTIPLIER \
        2>&1 | tee "${jobs_subdir}/${task_id}.log" \
        || {
            echo "WARNING: Task $task_id ($config) failed (exit code: $?)"
        }
}

_governance_run_single() {
    local task_id=$1
    local task_home=$2
    local config=${3:-baseline}
    local mcp_type=${4:-none}
    local jobs_base=${5:-$GOV_JOBS_BASE}
    local jobs_subdir="${jobs_base}/${config}"
    local task_path="${GOV_DIR}/${task_id}"

    mkdir -p "$jobs_subdir"

    if [ ! -d "$task_path" ]; then
        echo "ERROR: Task directory not found: $task_path"
        return 1
    fi

    echo "Running task: $task_id ($config) [HOME=$task_home]"

    local sg_repo="${TASK_SG_REPO_NAMES[$task_id]:-}"
    if [ -n "$sg_repo" ]; then
        export SOURCEGRAPH_REPO_NAME="$sg_repo"
    else
        unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
    fi

    BASELINE_MCP_TYPE=$mcp_type harbor run \
        --path "$task_path" \
        --agent-import-path "$AGENT_PATH" \
        --model "$MODEL" \
        --jobs-dir "$jobs_subdir" \
        -n $CONCURRENCY \
        --timeout-multiplier $TIMEOUT_MULTIPLIER \
        2>&1 | tee "${jobs_subdir}/${task_id}.log" \
        || {
            echo "WARNING: Task $task_id ($config) failed (exit code: $?)"
        }
}

# Metrics extraction helper
_extract_metrics() {
    local jobs_dir=$1
    local benchmark=$2
    local config=$3
    echo "Extracting per-task metrics from $jobs_dir..."
    for result_dir in "$jobs_dir"/*/*/; do
        if [ -f "$result_dir/result.json" ] && [ ! -f "$result_dir/task_metrics.json" ]; then
            python3 "$SCRIPT_DIR/../scripts/extract_task_metrics.py" \
                --task-dir "$result_dir" \
                --benchmark "$benchmark" \
                --config "$config" \
                --selected-tasks "$SELECTION_FILE" \
                2>&1 || echo "  WARNING: metrics extraction failed for $(basename $result_dir)"
        fi
    done
}

# ============================================
# MAIN EXECUTION
# ============================================
log_section() {
    echo ""
    echo "========================================"
    echo "$1"
    echo "========================================"
    echo ""
}

if [ "$RUN_BASELINE" = true ] && [ "$RUN_FULL" = true ]; then
    # Paired mode: enterprise tasks
    log_section "Phase 1: Enterprise Tasks (6 tasks x 2 configs)"
    run_paired_configs ENT_TASK_IDS _enterprise_run_single "$ENT_JOBS_BASE"

    for config in baseline sourcegraph_full; do
        if [ -d "${ENT_JOBS_BASE}/${config}" ]; then
            _extract_metrics "${ENT_JOBS_BASE}/${config}" "ccb_enterprise" "$config"
            validate_and_report "${ENT_JOBS_BASE}/${config}" "$config"
        fi
    done

    # Paired mode: governance tasks
    log_section "Phase 2: Governance Tasks (3 tasks x 2 configs)"
    ensure_fresh_token_all
    run_paired_configs GOV_TASK_IDS _governance_run_single "$GOV_JOBS_BASE"

    for config in baseline sourcegraph_full; do
        if [ -d "${GOV_JOBS_BASE}/${config}" ]; then
            _extract_metrics "${GOV_JOBS_BASE}/${config}" "ccb_governance" "$config"
            validate_and_report "${GOV_JOBS_BASE}/${config}" "$config"
        fi
    done
else
    # Single-config mode
    local_config="baseline"
    local_mcp="none"
    if [ "$RUN_FULL" = true ]; then
        local_config="sourcegraph_full"
        local_mcp="sourcegraph_full"
    fi

    ensure_fresh_token_all

    log_section "Enterprise Tasks ($local_config)"
    _ent_seq() {
        _enterprise_run_single "$1" "$2" "$local_config" "$local_mcp" "$ENT_JOBS_BASE"
    }
    run_tasks_parallel ENT_TASK_IDS _ent_seq || true
    _extract_metrics "${ENT_JOBS_BASE}/${local_config}" "ccb_enterprise" "$local_config"
    validate_and_report "${ENT_JOBS_BASE}/${local_config}" "$local_config"

    log_section "Governance Tasks ($local_config)"
    _gov_seq() {
        _governance_run_single "$1" "$2" "$local_config" "$local_mcp" "$GOV_JOBS_BASE"
    }
    run_tasks_parallel GOV_TASK_IDS _gov_seq || true
    _extract_metrics "${GOV_JOBS_BASE}/${local_config}" "ccb_governance" "$local_config"
    validate_and_report "${GOV_JOBS_BASE}/${local_config}" "$local_config"
fi

print_validation_summary "$ENT_JOBS_BASE"
print_validation_summary "$GOV_JOBS_BASE"

echo ""
echo "=============================================="
echo "De-hinted Rerun Complete!"
echo "=============================================="
echo "Enterprise results: ${ENT_JOBS_BASE}"
echo "Governance results: ${GOV_JOBS_BASE}"
echo ""
echo "Next steps:"
echo "  1. Rename old run dirs with __v1_hinted suffix"
echo "  2. Regenerate MANIFEST: python3 scripts/generate_manifest.py"
echo "  3. Rerun IR analysis: python3 scripts/ir_analysis.py"
