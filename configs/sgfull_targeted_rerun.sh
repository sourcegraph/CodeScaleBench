#!/bin/bash
# Targeted SG_full rerun for failed tasks only (beads-8t7)
# Sequences: SWE-bench Pro + RepoQA first, then K8s, then PyTorch
#
# Guardrails:
#   - Canary probe on batch 1 (first task validates infra before remaining 11)
#   - Token health check before each batch (stops on unrecoverable auth)
#   - Post-batch canary validation on single-task batches (2 & 3)
#   - Subscription-only auth enforcement
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

AGENT_DIR="${AGENT_DIR:-$HOME/evals/custom_agents/agents/claudecode}"
export PYTHONPATH="${AGENT_DIR}:$(pwd):$PYTHONPATH"
source "$SCRIPT_DIR/_common.sh"

if [ -f ~/evals/.env.local ]; then
    source ~/evals/.env.local
fi

# Subscription-only auth
enforce_subscription_mode

AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
MODEL="anthropic/claude-opus-4-6"
TIMEOUT_MULTIPLIER=10
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Enable canary by default for targeted reruns
CANARY_ENABLED=${CANARY_ENABLED:-true}

setup_dual_accounts

# Pre-flight token health
if ! check_token_health; then
    echo ""
    echo "FATAL: Token health check failed. Run:"
    echo "  python3 scripts/headless_login.py --all-accounts"
    exit 1
fi

echo "=============================================="
echo "Targeted SG_full Rerun (beads-8t7)"
echo "=============================================="
echo "Parallel jobs: ${PARALLEL_JOBS}"
echo "Canary: ${CANARY_ENABLED}"
echo ""

BATCH_RESULTS=()

# ============================================
# BATCH 1: SWE-bench Pro (11 failed tasks) + RepoQA (1 task)
# ============================================
echo ">>> BATCH 1: SWE-bench Pro (11 tasks) + RepoQA (1 task)"
echo ""

SWEPRO_JOBS="runs/official/swebenchpro_rerun_opus_${TIMESTAMP}/sourcegraph_full"
mkdir -p "$SWEPRO_JOBS"

# SWE-bench Pro SG repo mapping for failed tasks
declare -A SWEPRO_SG=(
    ["instance_ansible__ansible-b2a289dcbb702003377221e25f62c8a3608f0e89-v173091e2e36d38c978002990795f66cfc0af30ad"]="sg-benchmarks/ansible--b2a289dc"
    ["instance_internetarchive__openlibrary-92db3454aeaa02f89b4cdbc3103f7e95c9759f92-v2c55207218fb8a0138425cbf7d9675272e240b90"]="sg-benchmarks/openlibrary--92db3454"
    ["instance_navidrome__navidrome-9c3b4561652a15846993d477003e111f0df0c585"]="sg-benchmarks/navidrome--9c3b4561"
    ["instance_navidrome__navidrome-d0dceae0943b8df16e579c2d9437e11760a0626a"]="sg-benchmarks/navidrome--d0dceae0"
    ["instance_nodebb__nodebb-76c6e30282906ac664f2c9278fc90999b27b1f48-vd59a5728dfc977f44533186ace531248c2917516"]="sg-benchmarks/nodebb--76c6e302"
    ["instance_nodebb__nodebb-eb49a64974ca844bca061744fb3383f5d13b02ad-vnan"]="sg-benchmarks/nodebb--eb49a649"
    ["instance_nodebb__nodebb-f1a80d48cc45877fcbadf34c2345dd9709722c7f-v4fbcfae8b15e4ce5d132c408bca69ebb9cf146ed"]="sg-benchmarks/nodebb--f1a80d48"
    ["instance_protonmail__webclients-369fd37de29c14c690cb3b1c09a949189734026f"]="sg-benchmarks/webclients--369fd37d"
    ["instance_protonmail__webclients-8be4f6cb9380fcd2e67bcb18cef931ae0d4b869c"]="sg-benchmarks/webclients--8be4f6cb"
    ["instance_protonmail__webclients-c6f65d205c401350a226bb005f42fac1754b0b5b"]="sg-benchmarks/webclients--c6f65d20"
    ["instance_protonmail__webclients-caf10ba9ab2677761c88522d1ba8ad025779c492"]="sg-benchmarks/webclients--caf10ba9"
)

SWEPRO_TASKS=(
    "instance_ansible__ansible-b2a289dcbb702003377221e25f62c8a3608f0e89-v173091e2e36d38c978002990795f66cfc0af30ad"
    "instance_internetarchive__openlibrary-92db3454aeaa02f89b4cdbc3103f7e95c9759f92-v2c55207218fb8a0138425cbf7d9675272e240b90"
    "instance_navidrome__navidrome-9c3b4561652a15846993d477003e111f0df0c585"
    "instance_navidrome__navidrome-d0dceae0943b8df16e579c2d9437e11760a0626a"
    "instance_nodebb__nodebb-76c6e30282906ac664f2c9278fc90999b27b1f48-vd59a5728dfc977f44533186ace531248c2917516"
    "instance_nodebb__nodebb-eb49a64974ca844bca061744fb3383f5d13b02ad-vnan"
    "instance_nodebb__nodebb-f1a80d48cc45877fcbadf34c2345dd9709722c7f-v4fbcfae8b15e4ce5d132c408bca69ebb9cf146ed"
    "instance_protonmail__webclients-369fd37de29c14c690cb3b1c09a949189734026f"
    "instance_protonmail__webclients-8be4f6cb9380fcd2e67bcb18cef931ae0d4b869c"
    "instance_protonmail__webclients-c6f65d205c401350a226bb005f42fac1754b0b5b"
    "instance_protonmail__webclients-caf10ba9ab2677761c88522d1ba8ad025779c492"
)

_swepro_run_single() {
    local task_id=$1
    local task_home=$2
    local sg_repo="${SWEPRO_SG[$task_id]:-}"
    if [ -n "$sg_repo" ]; then
        export SOURCEGRAPH_REPO_NAME="$sg_repo"
        echo "  [sourcegraph_full] ${task_id} -> ${sg_repo} [HOME=$task_home]"
    fi
    BASELINE_MCP_TYPE=sourcegraph_full harbor run \
        --dataset swebenchpro \
        -t "$task_id" \
        --agent-import-path "$AGENT_PATH" \
        --model "$MODEL" \
        --jobs-dir "$SWEPRO_JOBS" \
        -n 2 \
        --timeout-multiplier $TIMEOUT_MULTIPLIER \
        2>&1 | tee "${SWEPRO_JOBS}/${task_id}.log" || true
}

# Also run RepoQA alongside SWE-bench Pro
REPOQA_JOBS="runs/official/repoqa_rerun_opus_${TIMESTAMP}/sourcegraph_full"
mkdir -p "$REPOQA_JOBS"
REPOQA_TASK="repoqa-cpp-skypjack-uvw-00"

_repoqa_run() {
    local task_id="$REPOQA_TASK"
    local task_home=$2
    local task_dir="benchmarks/ccb_repoqa/${task_id}"
    echo "  [sourcegraph_full] RepoQA ${task_id} [HOME=$task_home]"
    BASELINE_MCP_TYPE=sourcegraph_full harbor run \
        --path "$task_dir" \
        --agent-import-path "$AGENT_PATH" \
        --model "$MODEL" \
        --jobs-dir "$REPOQA_JOBS" \
        -n 2 \
        --timeout-multiplier 3 \
        2>&1 | tee "${REPOQA_JOBS}/${task_id}.log" || true
}

# Combine SWE-bench Pro + RepoQA into one batch
ALL_BATCH1_TASKS=("${SWEPRO_TASKS[@]}" "REPOQA_PLACEHOLDER")

_batch1_run_single() {
    local task_id=$1
    local task_home=$2
    if [ "$task_id" = "REPOQA_PLACEHOLDER" ]; then
        _repoqa_run "$task_id" "$task_home"
    else
        _swepro_run_single "$task_id" "$task_home"
    fi
}

# Canary: first task probes infra, remaining 11 only run if it's clean
run_canary_then_batch ALL_BATCH1_TASKS _batch1_run_single "$SWEPRO_JOBS" "sourcegraph_full"
batch1_exit=$?

if [ $batch1_exit -ne 0 ] && [ "$CANARY_ENABLED" = "true" ]; then
    echo "BATCH 1 BLOCKED by canary — stopping all batches"
    BATCH_RESULTS+=("batch1:blocked")
    echo ""
    echo "=============================================="
    echo "Targeted rerun ABORTED (canary stop signal)"
    echo "=============================================="
    echo "Check: ${SWEPRO_JOBS}/canary_verdict.json"
    exit 1
fi

BATCH_RESULTS+=("batch1:completed")
echo ""
echo ">>> BATCH 1 COMPLETE"
echo ""

# ============================================
# BATCH 2: K8s Docs (5 tasks) — separate
# ============================================
echo ">>> BATCH 2: K8s Docs (5 tasks)"
echo ""

# Token health gate
if ! check_token_health; then
    echo "BLOCKED: Token health check failed before K8s Docs batch"
    BATCH_RESULTS+=("batch2:blocked_auth")
    echo "Skipping remaining batches."
else
    CANARY_ENABLED=$CANARY_ENABLED bash configs/k8s_docs_3config.sh --full-only || true

    # Validate K8s result (k8s uses single harbor run, so check post-hoc)
    K8S_LATEST=$(ls -td runs/official/k8s_docs_opus_*/sourcegraph_full 2>/dev/null | head -1)
    if [ -n "$K8S_LATEST" ]; then
        if validate_canary_result "$K8S_LATEST" "sourcegraph_full"; then
            BATCH_RESULTS+=("batch2:completed")
        else
            echo "WARNING: K8s Docs had systemic issues (see canary_verdict.json)"
            BATCH_RESULTS+=("batch2:failed_canary")
        fi
    else
        echo "WARNING: No K8s Docs output directory found"
        BATCH_RESULTS+=("batch2:no_output")
    fi

    echo ""
    echo ">>> BATCH 2 COMPLETE"
    echo ""
fi

# ============================================
# BATCH 3: PyTorch sgt-025 (1 task) — separate
# ============================================
echo ">>> BATCH 3: PyTorch sgt-025 (1 task)"
echo ""

# Token health gate
if ! check_token_health; then
    echo "BLOCKED: Token health check failed before PyTorch batch"
    BATCH_RESULTS+=("batch3:blocked_auth")
else
    PYTORCH_JOBS="runs/official/pytorch_rerun_opus_${TIMESTAMP}/sourcegraph_full"
    mkdir -p "$PYTORCH_JOBS"

    SOURCEGRAPH_REPO_NAME="sg-benchmarks/pytorch--e8ca8cc3" \
    BASELINE_MCP_TYPE=sourcegraph_full harbor run \
        --path "benchmarks/ccb_pytorch/sgt-025" \
        --agent-import-path "$AGENT_PATH" \
        --model "$MODEL" \
        --jobs-dir "$PYTORCH_JOBS" \
        -n 2 \
        --timeout-multiplier 3 \
        2>&1 | tee "${PYTORCH_JOBS}/sgt-025.log" || true

    # Validate PyTorch result post-hoc
    if validate_canary_result "$PYTORCH_JOBS" "sourcegraph_full"; then
        BATCH_RESULTS+=("batch3:completed")
    else
        echo "WARNING: PyTorch sgt-025 had systemic issues"
        BATCH_RESULTS+=("batch3:failed_canary")
    fi

    echo ""
    echo ">>> BATCH 3 COMPLETE"
    echo ""
fi

# ============================================
# SUMMARY
# ============================================
echo "=============================================="
echo "Targeted Rerun Summary"
echo "=============================================="
for r in "${BATCH_RESULTS[@]}"; do
    echo "  $r"
done
echo ""
echo "SWE-bench Pro results: $SWEPRO_JOBS"
echo "RepoQA results: $REPOQA_JOBS"
echo "K8s Docs: check runs/official/k8s_docs_opus_*"
echo "PyTorch results: ${PYTORCH_JOBS:-skipped}"
