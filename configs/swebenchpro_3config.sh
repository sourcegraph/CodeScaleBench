#!/bin/bash
# SWE-bench Pro 50-Task 3-Config Comparison Script
#
# Runs all 50 SWE-bench Pro instances across 3 configurations:
#   1. Baseline (no MCP)
#   2. MCP-NoDeepSearch (Sourcegraph tools without Deep Search)
#   3. MCP-Full (Sourcegraph + Deep Search hybrid)
#
# Usage:
#   ./configs/swebenchpro_3config.sh [OPTIONS]
#
# Options:
#   --baseline-only        Run only baseline (no MCP)
#   --no-deepsearch-only   Run only MCP-NoDeepSearch
#   --full-only            Run only MCP-Full (sourcegraph_hybrid)
#   --model MODEL          Override model (default: claude-opus-4-5-20251101)
#   --concurrency N        Number of concurrent tasks (default: 2)
#   --category CATEGORY    Run category (default: official)
#
# Prerequisites:
#   - ~/evals/.env.local with ANTHROPIC_API_KEY (required)
#   - SOURCEGRAPH_ACCESS_TOKEN in .env.local (required for MCP modes)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# Add claudecode directory to PYTHONPATH for agent imports
export PYTHONPATH="$(pwd):$PYTHONPATH"

# ============================================
# LOAD CREDENTIALS
# ============================================
if [ -f ~/evals/.env.local ]; then
    echo "Loading credentials from ~/evals/.env.local..."
    source ~/evals/.env.local
else
    echo "Warning: ~/evals/.env.local not found"
    echo "Please create it with at minimum:"
    echo "  export ANTHROPIC_API_KEY=\"your-api-key\""
    echo ""
fi

# Verify required credentials
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: ANTHROPIC_API_KEY is not set"
    echo ""
    echo "Please set it in ~/evals/.env.local:"
    echo "  export ANTHROPIC_API_KEY=\"your-api-key\""
    exit 1
fi

echo "ANTHROPIC_API_KEY: set (${#ANTHROPIC_API_KEY} chars)"
if [ -n "$SOURCEGRAPH_ACCESS_TOKEN" ]; then
    echo "SOURCEGRAPH_ACCESS_TOKEN: set (${#SOURCEGRAPH_ACCESS_TOKEN} chars)"
else
    echo "SOURCEGRAPH_ACCESS_TOKEN: not set"
fi
echo ""

# ============================================
# CONFIGURATION
# ============================================
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
MODEL="${MODEL:-anthropic/claude-opus-4-5-20251101}"
CONCURRENCY=2
TIMEOUT_MULTIPLIER=10
RUN_BASELINE=true
RUN_NO_DEEPSEARCH=true
RUN_FULL=true
CATEGORY="${CATEGORY:-official}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --baseline-only)
            RUN_NO_DEEPSEARCH=false
            RUN_FULL=false
            shift
            ;;
        --no-deepsearch-only)
            RUN_BASELINE=false
            RUN_FULL=false
            shift
            ;;
        --full-only)
            RUN_BASELINE=false
            RUN_NO_DEEPSEARCH=false
            shift
            ;;
        --model)
            MODEL="$2"
            shift 2
            ;;
        --concurrency)
            CONCURRENCY="$2"
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

# Check MCP credentials if MCP modes requested
if { [ "$RUN_NO_DEEPSEARCH" = true ] || [ "$RUN_FULL" = true ]; } && [ -z "$SOURCEGRAPH_ACCESS_TOKEN" ]; then
    echo "WARNING: MCP modes requested but SOURCEGRAPH_ACCESS_TOKEN not set"
    echo "Skipping MCP runs. Use --baseline-only to suppress this warning."
    RUN_NO_DEEPSEARCH=false
    RUN_FULL=false
fi

# All 50 task IDs
TASK_IDS=(
    # Ansible (6 tasks)
    "instance_ansible__ansible-4c5ce5a1a9e79a845aff4978cfeb72a0d4ecf7d6-v1055803c3a812189a1133297f7f5468579283f86"
    "instance_ansible__ansible-811093f0225caa4dd33890933150a81c6a6d5226-v1055803c3a812189a1133297f7f5468579283f86"
    "instance_ansible__ansible-b8025ac160146319d2b875be3366b60c852dd35d-v0f01c69f1e2528b935359cfe578530722bca2c59"
    "instance_ansible__ansible-bec27fb4c0a40c5f8bbcf26a475704227d65ee73-v30a923fb5c164d6cd18280c02422f75e611e8fb2"
    "instance_ansible__ansible-c616e54a6e23fa5616a1d56d243f69576164ef9b-v1055803c3a812189a1133297f7f5468579283f86"
    "instance_ansible__ansible-e40889e7112ae00a21a2c74312b330e67a766cc0-v1055803c3a812189a1133297f7f5468579283f86"

    # Element-Web (2 tasks)
    "instance_element-hq__element-web-33e8edb3d508d6eefb354819ca693b7accc695e7"
    "instance_element-hq__element-web-f14374a51c153f64f313243f2df6ea4971db4e15"

    # Flipt (12 tasks)
    "instance_flipt-io__flipt-86906cbfc3a5d3629a583f98e6301142f5f14bdb-v6bea0cc3a6fc532d7da914314f2944fc1cd04dee"
    "instance_flipt-io__flipt-967855b429f749c28c112b8cb1b15bc79157f973"
    "instance_flipt-io__flipt-9d25c18b79bc7829a6fb08ec9e8793d5d17e2868"
    "instance_flipt-io__flipt-aebaecd026f752b187f11328b0d464761b15d2ab"
    "instance_flipt-io__flipt-b3cd920bbb25e01fdb2dab66a5a913363bc62f6c"
    "instance_flipt-io__flipt-b433bd05ce405837804693bebd5f4b88d87133c8"
    "instance_flipt-io__flipt-c1fd7a81ef9f23e742501bfb26d914eb683262aa"
    "instance_flipt-io__flipt-c8d71ad7ea98d97546f01cce4ccb451dbcf37d3b"
    "instance_flipt-io__flipt-cf06f4ebfab7fa21eed3e5838592e8e44566957f"
    "instance_flipt-io__flipt-dbe263961b187e1c5d7fe34c65b000985a2da5a0"
    "instance_flipt-io__flipt-e91615cf07966da41756017a7d571f9fc0fdbe80"
    "instance_flipt-io__flipt-f1bc91a1b999656dbdb2495ccb57bf2105b84920"

    # Future Architect/Vuls (5 tasks)
    "instance_future-architect__vuls-139f3a81b66c47e6d8f70ce6c4afe7a9196a6ea8"
    "instance_future-architect__vuls-4a72295de7b91faa59d90a5bee91535bbe76755d"
    "instance_future-architect__vuls-ad2edbb8448e2c41a097f1c0b52696c0f6c5924d"
    "instance_future-architect__vuls-e049df50fa1eecdccc5348e27845b5c783ed7c76-v73dc95f6b90883d8a87e01e5e9bb6d3cc32add6d"
    "instance_future-architect__vuls-e1fab805afcfc92a2a615371d0ec1e667503c254-v264a82e2f4818e30f5a25e4da53b27ba119f62b5"

    # Gravitational/Teleport (9 tasks)
    "instance_gravitational__teleport-288c5519ce0dec9622361a5e5d6cd36aa2d9e348"
    "instance_gravitational__teleport-3587cca7840f636489449113969a5066025dd5bf"
    "instance_gravitational__teleport-3fa6904377c006497169945428e8197158667910-v626ec2a48416b10a88641359a169d99e935ff037"
    "instance_gravitational__teleport-6eaaf3a27e64f4ef4ef855bd35d7ec338cf17460-v626ec2a48416b10a88641359a169d99e935ff037"
    "instance_gravitational__teleport-7744f72c6eb631791434b648ba41083b5f6d2278-vce94f93ad1030e3136852817f2423c1b3ac37bc4"
    "instance_gravitational__teleport-d6ffe82aaf2af1057b69c61bf9df777f5ab5635a-vee9b09fb20c43af7e520f57e9239bbcf46b7113d"
    "instance_gravitational__teleport-d873ea4fa67d3132eccba39213c1ca2f52064dcc-vce94f93ad1030e3136852817f2423c1b3ac37bc4"
    "instance_gravitational__teleport-db89206db6c2969266e664c7c0fb51b70e958b64"
    "instance_gravitational__teleport-fb0ab2b9b771377a689fd0d0374777c251e58bbf"

    # Internet Archive/OpenLibrary (5 tasks)
    "instance_internetarchive__openlibrary-7f6b722a10f822171501d027cad60afe53337732-ve8c8d62a2b60610a3c4631f5f23ed866bada9818"
    "instance_internetarchive__openlibrary-92db3454aeaa02f89b4cdbc3103f7e95c9759f92-v2c55207218fb8a0138425cbf7d9675272e240b90"
    "instance_internetarchive__openlibrary-b67138b316b1e9c11df8a4a8391fe5cc8e75ff9f-ve8c8d62a2b60610a3c4631f5f23ed866bada9818"
    "instance_internetarchive__openlibrary-bb152d23c004f3d68986877143bb0f83531fe401-ve8c8d62a2b60610a3c4631f5f23ed866bada9818"
    "instance_internetarchive__openlibrary-d109cc7e6e161170391f98f9a6fa1d02534c18e4-ve8c8d62a2b60610a3c4631f5f23ed866bada9818"

    # Navidrome (1 task)
    "instance_navidrome__navidrome-bf2bcb12799b21069f137749e0c331f761d1f693"

    # NodeBB (2 tasks)
    "instance_NodeBB__NodeBB-76c6e30282906ac664f2c9278fc90999b27b1f48-vd59a5728dfc977f44533186ace531248c2917516"
    "instance_NodeBB__NodeBB-f1a80d48cc45877fcbadf34c2345dd9709722c7f-v4fbcfae8b15e4ce5d132c408bca69ebb9cf146ed"

    # ProtonMail/Webclients (7 tasks)
    "instance_protonmail__webclients-0d0267c4438cf378bda90bc85eed3a3615871ac4"
    "instance_protonmail__webclients-2dce79ea4451ad88d6bfe94da22e7f2f988efa60"
    "instance_protonmail__webclients-369fd37de29c14c690cb3b1c09a949189734026f"
    "instance_protonmail__webclients-6e1873b06df6529a469599aa1d69d3b18f7d9d37"
    "instance_protonmail__webclients-8be4f6cb9380fcd2e67bcb18cef931ae0d4b869c"
    "instance_protonmail__webclients-c6f65d205c401350a226bb005f42fac1754b0b5b"
    "instance_protonmail__webclients-caf10ba9ab2677761c88522d1ba8ad025779c492"

    # Tutao/Tutanota (1 task)
    "instance_tutao__tutanota-befce4b146002b9abc86aa95f4d57581771815ce-vee878bb72091875e912c52fc32bc60ec3760227b"
)

# Derive short model name for run directory (matches V2 id_generator convention)
_model_lower=$(echo "$MODEL" | awk -F/ '{print $NF}' | tr '[:upper:]' '[:lower:]')
case "$_model_lower" in
    *opus*)   MODEL_SHORT="opus" ;;
    *sonnet*) MODEL_SHORT="sonnet" ;;
    *haiku*)  MODEL_SHORT="haiku" ;;
    *gpt-4o*|*gpt4o*) MODEL_SHORT="gpt4o" ;;
    *gpt-4*|*gpt4*)   MODEL_SHORT="gpt4" ;;
    *)        MODEL_SHORT=$(echo "$_model_lower" | tr -d '-' | tr -d '_' | cut -c1-8) ;;
esac

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
JOBS_BASE="runs/${CATEGORY}/swebenchpro_50_tasks_${MODEL_SHORT}_${TIMESTAMP}"

echo "=============================================="
echo "SWE-bench Pro 50-Task 3-Config Benchmark"
echo "=============================================="
echo "Model: ${MODEL}"
echo "Tasks: ${#TASK_IDS[@]}"
echo "Concurrency: ${CONCURRENCY}"
echo "Timeout multiplier: ${TIMEOUT_MULTIPLIER}x"
echo "Jobs directory: ${JOBS_BASE}"
echo "Run baseline: ${RUN_BASELINE}"
echo "Run MCP-NoDeepSearch: ${RUN_NO_DEEPSEARCH}"
echo "Run MCP-Full: ${RUN_FULL}"
echo ""

# Create jobs directory
mkdir -p "${JOBS_BASE}"

# Build task name arguments
TASK_NAME_ARGS=""
for task_id in "${TASK_IDS[@]}"; do
    TASK_NAME_ARGS="${TASK_NAME_ARGS} -t ${task_id}"
done

# ============================================
# RUN BASELINE (no MCP)
# ============================================
if [ "$RUN_BASELINE" = true ]; then
    echo ""
    echo "[BASELINE] Starting 50-task baseline run..."
    echo ""

    BASELINE_MCP_TYPE=none harbor run \
        --dataset swebenchpro \
        ${TASK_NAME_ARGS} \
        --agent-import-path "${AGENT_PATH}" \
        --model "${MODEL}" \
        --jobs-dir "${JOBS_BASE}/baseline" \
        -n ${CONCURRENCY} \
        --timeout-multiplier ${TIMEOUT_MULTIPLIER} \
        2>&1 | tee "${JOBS_BASE}/baseline.log"
fi

# ============================================
# RUN MCP-NoDeepSearch (sourcegraph_no_deepsearch)
# ============================================
if [ "$RUN_NO_DEEPSEARCH" = true ]; then
    echo ""
    echo "[MCP-NoDeepSearch] Starting 50-task MCP-NoDeepSearch run..."
    echo ""

    BASELINE_MCP_TYPE=sourcegraph_no_deepsearch harbor run \
        --dataset swebenchpro \
        ${TASK_NAME_ARGS} \
        --agent-import-path "${AGENT_PATH}" \
        --model "${MODEL}" \
        --jobs-dir "${JOBS_BASE}/sourcegraph_no_deepsearch" \
        -n ${CONCURRENCY} \
        --timeout-multiplier ${TIMEOUT_MULTIPLIER} \
        2>&1 | tee "${JOBS_BASE}/sourcegraph_no_deepsearch.log"
fi

# ============================================
# RUN MCP-Full (sourcegraph_hybrid)
# ============================================
if [ "$RUN_FULL" = true ]; then
    echo ""
    echo "[MCP-Full] Starting 50-task MCP-Full run..."
    echo ""

    BASELINE_MCP_TYPE=sourcegraph_hybrid harbor run \
        --dataset swebenchpro \
        ${TASK_NAME_ARGS} \
        --agent-import-path "${AGENT_PATH}" \
        --model "${MODEL}" \
        --jobs-dir "${JOBS_BASE}/sourcegraph_hybrid" \
        -n ${CONCURRENCY} \
        --timeout-multiplier ${TIMEOUT_MULTIPLIER} \
        2>&1 | tee "${JOBS_BASE}/sourcegraph_hybrid.log"
fi

echo ""
echo "=============================================="
echo "Benchmark Complete!"
echo "=============================================="
echo "Results saved to: ${JOBS_BASE}"
echo ""
echo "View results:"
if [ "$RUN_BASELINE" = true ]; then
    echo "  # Baseline - count resolved"
    echo "  cat ${JOBS_BASE}/baseline/*/result.json | jq -s '[.[] | select(.trials[].verifier_result.resolved == true)] | length'"
    echo ""
fi
if [ "$RUN_NO_DEEPSEARCH" = true ]; then
    echo "  # MCP-NoDeepSearch - count resolved"
    echo "  cat ${JOBS_BASE}/sourcegraph_no_deepsearch/*/result.json | jq -s '[.[] | select(.trials[].verifier_result.resolved == true)] | length'"
    echo ""
fi
if [ "$RUN_FULL" = true ]; then
    echo "  # MCP-Full - count resolved"
    echo "  cat ${JOBS_BASE}/sourcegraph_hybrid/*/result.json | jq -s '[.[] | select(.trials[].verifier_result.resolved == true)] | length'"
fi
