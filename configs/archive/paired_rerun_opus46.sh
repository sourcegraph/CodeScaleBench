#!/bin/bash
# Paired 2-Config Rerun — Opus 4.6 Interleaved Baseline + SG_full
#
# Runs BOTH baseline (no MCP) and SG_full (MCP preamble) for the same tasks,
# interleaved in the parallel queue so both configs experience similar system load.
#
# Jobs are queued as: BL:task1, SF:task1, BL:task2, SF:task2, ...
# With 8 parallel slots, ~4 baseline and ~4 SG_full run concurrently.
#
# Usage:
#   ./configs/paired_rerun_opus46.sh --suite ccb_pytorch [OPTIONS]
#
# Options:
#   --suite SUITE      Required. Which benchmark to run (e.g. ccb_pytorch)
#   --parallel N       Number of parallel task subshells (default: auto)
#   --dry-run          Print job list without running
#   --baseline-only    Run only baseline config
#   --full-only        Run only SG_full config
#
# Supported suites (need baseline Opus 4.6 reruns):
#   ccb_pytorch, ccb_locobench, ccb_swebenchpro, ccb_repoqa,
#   ccb_dibench, ccb_linuxflbench, ccb_codereview, ccb_sweperf

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
SELECTION_FILE="$SCRIPT_DIR/selected_benchmark_tasks.json"
BENCHMARKS_DIR="/home/stephanie_jarmak/CodeContextBench/benchmarks"
DRY_RUN=false
SUITE=""
RUN_BASELINE=true
RUN_FULL=true

while [[ $# -gt 0 ]]; do
    case $1 in
        --suite)
            SUITE="$2"
            shift 2
            ;;
        --parallel)
            PARALLEL_JOBS="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --baseline-only)
            RUN_FULL=false
            shift
            ;;
        --full-only)
            RUN_BASELINE=false
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

if [ -z "$SUITE" ]; then
    echo "ERROR: --suite is required"
    echo "Usage: $0 --suite ccb_pytorch [--dry-run] [--parallel N]"
    exit 1
fi

setup_dual_accounts

if [ "$DRY_RUN" != true ]; then
    if ! check_token_health; then
        echo "FATAL: Token health check failed. Run:"
        echo "  python3 scripts/headless_login.py --all-accounts"
        exit 1
    fi
fi

# ============================================
# SUITE CONFIG: tasks_dir + SG repo mappings
# ============================================
# Each suite needs: TASKS_DIR, HARBOR_MODE (path|dataset), and SG repo mapping

declare -A SG_REPO_MAP  # populated per-suite below
TASKS_DIR=""
HARBOR_MODE="path"
SG_REPO_DYNAMIC=""  # set to function name if dynamic resolution needed

case "$SUITE" in
    ccb_pytorch)
        TASKS_DIR="${BENCHMARKS_DIR}/ccb_pytorch"
        declare -A SG_REPO_MAP=(
            ["sgt-001"]="sg-benchmarks/pytorch--ca246612"
            ["sgt-002"]="sg-benchmarks/pytorch--ca246612"
            ["sgt-003"]="sg-benchmarks/pytorch--d18007a1"
            ["sgt-005"]="sg-benchmarks/pytorch--ca246612"
            ["sgt-008"]="sg-benchmarks/pytorch--863edc78"
            ["sgt-009"]="sg-benchmarks/pytorch--863edc78"
            ["sgt-010"]="sg-benchmarks/pytorch--5811a8d7"
            ["sgt-012"]="sg-benchmarks/pytorch--e3e93c71"
            ["sgt-014"]="sg-benchmarks/pytorch--cbe1a35d"
            ["sgt-016"]="sg-benchmarks/pytorch--cbe1a35d"
            ["sgt-021"]="sg-benchmarks/pytorch--cbe1a35d"
            ["sgt-025"]="sg-benchmarks/pytorch--e8ca8cc3"
        )
        ;;
    ccb_locobench)
        TASKS_DIR="${BENCHMARKS_DIR}/ccb_locobench/tasks"
        SG_REPO_DYNAMIC="locobench"  # resolve from docker-compose.yaml
        ;;
    ccb_swebenchpro)
        TASKS_DIR=""  # uses --dataset mode
        HARBOR_MODE="dataset"
        declare -A SG_REPO_MAP=(
            ["instance_nodebb__nodebb-76c6e30282906ac664f2c9278fc90999b27b1f48-vd59a5728dfc977f44533186ace531248c2917516"]="sg-benchmarks/nodebb--76c6e302"
            ["instance_nodebb__nodebb-eb49a64974ca844bca061744fb3383f5d13b02ad-vnan"]="sg-benchmarks/nodebb--eb49a649"
            ["instance_nodebb__nodebb-f1a80d48cc45877fcbadf34c2345dd9709722c7f-v4fbcfae8b15e4ce5d132c408bca69ebb9cf146ed"]="sg-benchmarks/nodebb--f1a80d48"
            ["instance_ansible__ansible-379058e10f3dbc0fdcaf80394bd09b18927e7d33-v1055803c3a812189a1133297f7f5468579283f86"]="sg-benchmarks/ansible--379058e1"
            ["instance_ansible__ansible-4c5ce5a1a9e79a845aff4978cfeb72a0d4ecf7d6-v1055803c3a812189a1133297f7f5468579283f86"]="sg-benchmarks/ansible--4c5ce5a1"
            ["instance_ansible__ansible-811093f0225caa4dd33890933150a81c6a6d5226-v1055803c3a812189a1133297f7f5468579283f86"]="sg-benchmarks/ansible--811093f0"
            ["instance_ansible__ansible-b2a289dcbb702003377221e25f62c8a3608f0e89-v173091e2e36d38c978002990795f66cfc0af30ad"]="sg-benchmarks/ansible--b2a289dc"
            ["instance_ansible__ansible-e40889e7112ae00a21a2c74312b330e67a766cc0-v1055803c3a812189a1133297f7f5468579283f86"]="sg-benchmarks/ansible--e40889e7"
            ["instance_element-hq__element-web-cf3c899dd1f221aa1a1f4c5a80dffc05b9c21c85-vnan"]="sg-benchmarks/element-web--cf3c899d"
            ["instance_element-hq__element-web-f14374a51c153f64f313243f2df6ea4971db4e15"]="sg-benchmarks/element-web--f14374a5"
            ["instance_flipt-io__flipt-3d5a345f94c2adc8a0eaa102c189c08ad4c0f8e8"]="sg-benchmarks/flipt--3d5a345f"
            ["instance_flipt-io__flipt-9f8127f225a86245fa35dca4885c2daef824ee55"]="sg-benchmarks/flipt--9f8127f2"
            ["instance_flipt-io__flipt-b433bd05ce405837804693bebd5f4b88d87133c8"]="sg-benchmarks/flipt--b433bd05"
            ["instance_flipt-io__flipt-c188284ff0c094a4ee281afebebd849555ebee59"]="sg-benchmarks/flipt--c188284f"
            ["instance_future-architect__vuls-139f3a81b66c47e6d8f70ce6c4afe7a9196a6ea8"]="sg-benchmarks/vuls--139f3a81"
            ["instance_future-architect__vuls-4c04acbd9ea5b073efe999e33381fa9f399d6f27"]="sg-benchmarks/vuls--4c04acbd"
            ["instance_future-architect__vuls-d18e7a751d07260d75ce3ba0cd67c4a6aebfd967"]="sg-benchmarks/vuls--d18e7a75"
            ["instance_gravitational__teleport-0415e422f12454db0c22316cf3eaa5088d6b6322"]="sg-benchmarks/teleport--0415e422"
            ["instance_gravitational__teleport-3587cca7840f636489449113969a5066025dd5bf"]="sg-benchmarks/teleport--3587cca7"
            ["instance_gravitational__teleport-7744f72c6eb631791434b648ba41083b5f6d2278-vce94f93ad1030e3136852817f2423c1b3ac37bc4"]="sg-benchmarks/teleport--7744f72c"
            ["instance_gravitational__teleport-8302d467d160f869b77184e262adbe2fbc95d9ba-vce94f93ad1030e3136852817f2423c1b3ac37bc4"]="sg-benchmarks/teleport--8302d467"
            ["instance_internetarchive__openlibrary-7f6b722a10f822171501d027cad60afe53337732-ve8c8d62a2b60610a3c4631f5f23ed866bada9818"]="sg-benchmarks/openlibrary--7f6b722a"
            ["instance_internetarchive__openlibrary-92db3454aeaa02f89b4cdbc3103f7e95c9759f92-v2c55207218fb8a0138425cbf7d9675272e240b90"]="sg-benchmarks/openlibrary--92db3454"
            ["instance_internetarchive__openlibrary-c506c1b0b678892af5cb22c1c1dbc35d96787a0a-v0f5aece3601a5b4419f7ccec1dbda2071be28ee4"]="sg-benchmarks/openlibrary--c506c1b0"
            ["instance_internetarchive__openlibrary-d109cc7e6e161170391f98f9a6fa1d02534c18e4-ve8c8d62a2b60610a3c4631f5f23ed866bada9818"]="sg-benchmarks/openlibrary--d109cc7e"
            ["instance_navidrome__navidrome-9c3b4561652a15846993d477003e111f0df0c585"]="sg-benchmarks/navidrome--9c3b4561"
            ["instance_navidrome__navidrome-d0dceae0943b8df16e579c2d9437e11760a0626a"]="sg-benchmarks/navidrome--d0dceae0"
            ["instance_protonmail__webclients-369fd37de29c14c690cb3b1c09a949189734026f"]="sg-benchmarks/webclients--369fd37d"
            ["instance_protonmail__webclients-8be4f6cb9380fcd2e67bcb18cef931ae0d4b869c"]="sg-benchmarks/webclients--8be4f6cb"
            ["instance_protonmail__webclients-c6f65d205c401350a226bb005f42fac1754b0b5b"]="sg-benchmarks/webclients--c6f65d20"
            ["instance_protonmail__webclients-caf10ba9ab2677761c88522d1ba8ad025779c492"]="sg-benchmarks/webclients--caf10ba9"
            ["instance_qutebrowser__qutebrowser-233cb1cc48635130e5602549856a6fa4ab4c087f-v35616345bb8052ea303186706cec663146f0f184"]="sg-benchmarks/qutebrowser--233cb1cc"
            ["instance_qutebrowser__qutebrowser-394bfaed6544c952c6b3463751abab3176ad4997-vafb3e8e01b31319c66c4e666b8a3b1d8ba55db24"]="sg-benchmarks/qutebrowser--394bfaed"
            ["instance_qutebrowser__qutebrowser-3fd8e12949b8feda401930574facf09dd4180bba"]="sg-benchmarks/qutebrowser--3fd8e129"
            ["instance_qutebrowser__qutebrowser-e5340c449f23608803c286da0563b62f58ba25b0-v059c6fdc75567943479b23ebca7c07b5e9a7f34c"]="sg-benchmarks/qutebrowser--e5340c44"
            ["instance_tutao__tutanota-f373ac3808deefce8183dad8d16729839cc330c1-v2939aa9f4356f0dc9f523ee5ce19d09e08ab979b"]="sg-benchmarks/tutanota--f373ac38"
        )
        ;;
    ccb_repoqa)
        TASKS_DIR="${BENCHMARKS_DIR}/ccb_repoqa/tasks"
        declare -A SG_REPO_MAP=(
            ["ccb_repoqa-cpp-apache-logging-log4cxx-03"]="sg-benchmarks/apache--logging-log4cxx--502f5711"
            ["ccb_repoqa-cpp-mysql-mysql-server-05"]="sg-benchmarks/mysql--mysql-server--b8f15dd7"
            ["ccb_repoqa-go-envoyproxy-envoy-01"]="sg-benchmarks/envoyproxy--envoy--44531122"
            ["ccb_repoqa-java-apache-doris-03"]="sg-benchmarks/apache--doris--b43ed68e"
            ["ccb_repoqa-java-elastic-elasticsearch-01"]="sg-benchmarks/elastic--elasticsearch--f0a3799b"
            ["ccb_repoqa-python-apache-airflow-02"]="sg-benchmarks/apache--airflow--94db14dc"
            ["ccb_repoqa-python-dask-dask-04"]="sg-benchmarks/dask--dask--a8b0fba0"
            ["ccb_repoqa-rust-nickel-org-nickel-05"]="sg-benchmarks/nickel-org--nickel--58ba9271"
            ["ccb_repoqa-rust-servo-servo-01"]="sg-benchmarks/servo--servo--ab5bc3dd"
            ["ccb_repoqa-typescript-blitz-js-blitz-02"]="sg-benchmarks/blitz-js--blitz--e93bbf4c"
        )
        ;;
    ccb_dibench)
        TASKS_DIR="${BENCHMARKS_DIR}/ccb_dibench"
        declare -A SG_REPO_MAP=(
            ["ccb_dibench-python-inducer-cgen"]="sg-benchmarks/cgen--dibench"
            ["ccb_dibench-python-mitmproxy-pdoc"]="sg-benchmarks/pdoc--dibench"
            ["ccb_dibench-python-pydata-xarray"]="sg-benchmarks/xarray--dibench"
            ["ccb_dibench-python-python-attrs-cattrs"]="sg-benchmarks/cattrs--dibench"
            ["ccb_dibench-javascript-expressjs-express"]="sg-benchmarks/express--dibench"
            ["ccb_dibench-javascript-mozilla-readability"]="sg-benchmarks/readability--dibench"
            ["ccb_dibench-typescript-graphql-graphql-js"]="sg-benchmarks/graphql-js--dibench"
            ["ccb_dibench-typescript-nodeca-js-yaml"]="sg-benchmarks/js-yaml--dibench"
        )
        ;;
    ccb_linuxflbench)
        TASKS_DIR="${BENCHMARKS_DIR}/ccb_linuxflbench"
        declare -A SG_REPO_MAP=(
            ["lfl-acpi-207835"]="github.com/sg-benchmarks/linux--55b2af1c"
            ["lfl-cpufreq-214059"]="github.com/sg-benchmarks/linux--0b403e06"
            ["lfl-ipv4-208956"]="github.com/sg-benchmarks/linux--e7aabfa4"
            ["lfl-locking-209891"]="github.com/sg-benchmarks/linux--6a0129e2"
            ["lfl-usb-214093"]="github.com/sg-benchmarks/linux--0b403e06"
        )
        ;;
    ccb_codereview)
        TASKS_DIR="${BENCHMARKS_DIR}/ccb_codereview"
        declare -A SG_REPO_MAP=(
            ["cr-aspnetcore-001"]="github.com/sg-benchmarks/aspnetcore--87525573"
            ["cr-coder-001"]="github.com/sg-benchmarks/coder--af18baab"
            ["cr-multi-001"]="github.com/sg-benchmarks/aspnetcore--87525573"
        )
        ;;
    ccb_sweperf)
        TASKS_DIR="${BENCHMARKS_DIR}/ccb_sweperf/tasks"
        declare -A SG_REPO_MAP=(
            ["ccb_sweperf-001"]="sg-benchmarks/numpy--a639fbf5"
            ["ccb_sweperf-002"]="sg-benchmarks/scikit-learn--c1949e7e"
            ["ccb_sweperf-003"]="sg-benchmarks/pandas--e8325343"
        )
        ;;
    *)
        echo "ERROR: Unsupported suite: $SUITE"
        echo "Supported: ccb_pytorch, ccb_locobench, ccb_swebenchpro, ccb_repoqa, ccb_dibench, ccb_linuxflbench, ccb_codereview, ccb_sweperf"
        exit 1
        ;;
esac

# ============================================
# LOAD TASKS + BUILD INTERLEAVED JOB LIST
# ============================================
readarray -t RAW_TASK_IDS < <(python3 -c "
import json
tasks = json.load(open('$SELECTION_FILE'))['tasks']
for t in tasks:
    if t['benchmark'] == '$SUITE':
        print(t['task_id'])
")

if [ ${#RAW_TASK_IDS[@]} -eq 0 ]; then
    echo "ERROR: No tasks found for $SUITE in $SELECTION_FILE"
    exit 1
fi

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SUITE_SHORT="${SUITE#ccb_}"
JOBS_BASE="runs/official/${SUITE_SHORT}_paired_opus_${TIMESTAMP}"
BL_DIR="${JOBS_BASE}/baseline"
SF_DIR="${JOBS_BASE}/sourcegraph_full"

# Build interleaved job list: BL:task1, SF:task1, BL:task2, SF:task2, ...
PAIRED_JOBS=()
for task_id in "${RAW_TASK_IDS[@]}"; do
    if [ "$RUN_BASELINE" = true ]; then
        PAIRED_JOBS+=("BL:${task_id}")
    fi
    if [ "$RUN_FULL" = true ]; then
        PAIRED_JOBS+=("SF:${task_id}")
    fi
done

NUM_BL=0; NUM_SF=0
for j in "${PAIRED_JOBS[@]}"; do
    case "${j%%:*}" in BL) NUM_BL=$((NUM_BL + 1)) ;; SF) NUM_SF=$((NUM_SF + 1)) ;; esac
done

echo "=============================================="
echo "Paired 2-Config Rerun — ${SUITE}"
echo "=============================================="
echo "Model: ${MODEL}"
echo "Tasks: ${#RAW_TASK_IDS[@]} × (${NUM_BL:+BL}${NUM_SF:+ SF}) = ${#PAIRED_JOBS[@]} jobs"
echo "Parallel jobs: ${PARALLEL_JOBS}"
echo "Jobs base: ${JOBS_BASE}"
echo "Baseline dir: ${BL_DIR}"
echo "SG_full dir:  ${SF_DIR}"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo "Job queue (interleaved):"
    for j in "${PAIRED_JOBS[@]}"; do
        local_cfg="${j%%:*}"
        local_task="${j#*:}"
        printf "  %-3s  %s\n" "$local_cfg" "$local_task"
    done
    echo ""
    echo "Total: ${#PAIRED_JOBS[@]} jobs (${NUM_BL} baseline + ${NUM_SF} SG_full)"
    exit 0
fi

mkdir -p "$BL_DIR" "$SF_DIR"
ensure_fresh_token_all

# ============================================
# LOCOBENCH DYNAMIC SG REPO RESOLUTION
# ============================================
_resolve_sg_repo_locobench() {
    local task_id=$1
    local task_dir="${TASKS_DIR}/${task_id}"
    local compose_file="${task_dir}/environment/docker-compose.yaml"
    if [ -f "$compose_file" ]; then
        local proj_id
        proj_id=$(python3 -c "
import yaml, sys
d = yaml.safe_load(open('$compose_file'))
envs = d.get('services',{}).get('default',{}).get('environment',{})
print(envs.get('LOCOBENCH_PROJECT_ID',''))
" 2>/dev/null)
        if [ -n "$proj_id" ]; then
            echo "sg-benchmarks/locobench-${proj_id}"
            return
        fi
    fi
    echo ""
}

# ============================================
# DISPATCH FUNCTION (called by parallel runner)
# ============================================
# Receives composite "CONFIG:TASK_ID" as $1, account home as $2
_dispatch_job() {
    local composite=$1
    local task_home=$2
    local config="${composite%%:*}"
    local task_id="${composite#*:}"

    local mcp_type jobs_dir
    if [ "$config" = "BL" ]; then
        mcp_type="none"
        jobs_dir="$BL_DIR"
    else
        mcp_type="sourcegraph_full"
        jobs_dir="$SF_DIR"
    fi

    # Resolve SG repo name for MCP mode
    if [ "$config" = "SF" ]; then
        if [ "$SG_REPO_DYNAMIC" = "locobench" ]; then
            local sg_repo
            sg_repo=$(_resolve_sg_repo_locobench "$task_id")
        else
            local sg_repo="${SG_REPO_MAP[$task_id]:-}"
        fi
        if [ -n "$sg_repo" ]; then
            export SOURCEGRAPH_REPO_NAME="$sg_repo"
        else
            unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
        fi
    else
        unset SOURCEGRAPH_REPO_NAME 2>/dev/null || true
    fi

    echo "  [${config}] ${task_id} [HOME=$(basename $task_home)]"

    if [ "$HARBOR_MODE" = "dataset" ]; then
        BASELINE_MCP_TYPE=$mcp_type harbor run \
            --dataset swebenchpro \
            -t "$task_id" \
            --agent-import-path "$AGENT_PATH" \
            --model "$MODEL" \
            --jobs-dir "$jobs_dir" \
            -n $CONCURRENCY \
            --timeout-multiplier $TIMEOUT_MULTIPLIER \
            2>&1 | tee "${jobs_dir}/${config}_${task_id}.log" || true
    else
        local task_path="${TASKS_DIR}/${task_id}"
        if [ ! -d "$task_path" ]; then
            echo "SKIP: Task directory not found: $task_path"
            return 0
        fi
        BASELINE_MCP_TYPE=$mcp_type harbor run \
            --path "$task_path" \
            --agent-import-path "$AGENT_PATH" \
            --model "$MODEL" \
            --jobs-dir "$jobs_dir" \
            -n $CONCURRENCY \
            --timeout-multiplier $TIMEOUT_MULTIPLIER \
            2>&1 | tee "${jobs_dir}/${config}_${task_id}.log" || true
    fi
}

# ============================================
# MAIN EXECUTION
# ============================================
echo "Launching ${#PAIRED_JOBS[@]} interleaved jobs..."
echo ""

# Use the parallel runner directly (skip canary for paired runs — tasks are proven)
export CANARY_ENABLED=false
run_tasks_parallel PAIRED_JOBS _dispatch_job

# Post-run validation
echo ""
echo "=============================================="
echo "Post-run Validation"
echo "=============================================="
if [ "$RUN_BASELINE" = true ]; then
    validate_and_report "$BL_DIR" "baseline"
fi
if [ "$RUN_FULL" = true ]; then
    validate_and_report "$SF_DIR" "sourcegraph_full"
fi

# Quick summary
echo ""
echo "=============================================="
echo "Paired Run Complete — ${SUITE}"
echo "=============================================="
echo "Results: ${JOBS_BASE}"
echo ""
echo "Quick comparison:"
echo "  # Baseline results"
echo "  cat ${BL_DIR}/*/*/result.json 2>/dev/null | jq -r '.trials[].verifier_result.rewards.reward // .trials[].verifier_result.rewards.score'"
echo ""
echo "  # SG_full results"
echo "  cat ${SF_DIR}/*/*/result.json 2>/dev/null | jq -r '.trials[].verifier_result.rewards.reward // .trials[].verifier_result.rewards.score'"
echo ""
echo "Regenerate MANIFEST: python3 scripts/generate_manifest.py"
