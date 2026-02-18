#!/bin/bash
# Overnight Benchmark Orchestrator
#
# Runs multiple benchmarks sequentially with token health checks between each.
# Uses canary guardrails to detect systemic failures early.
#
# Usage:
#   nohup ./configs/run_overnight.sh [OPTIONS] 2>&1 | tee overnight.log &
#
# Options:
#   --benchmarks "b1 b2 ..."   Space-separated benchmark names (default: all)
#   --configs "c1 c2 ..."      Configs to pass: baseline-only, base-only, full-only (default: all 3)
#   --parallel N               Override parallel job count
#   --dry-run                  Print what would run without executing
#   --resume-from BENCHMARK    Skip benchmarks before this one
#   --no-canary                Disable canary checks (fall through to normal parallel)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

source "$SCRIPT_DIR/_common.sh"

# Load credentials
if [ -f ~/evals/.env.local ]; then
    source ~/evals/.env.local
fi

# ============================================
# BENCHMARK REGISTRY
# ============================================
# Maps benchmark name to its 3config script.
declare -A BENCHMARK_SCRIPTS=(
    ["codereview"]="codereview_3config.sh"
    ["pytorch"]="pytorch_3config.sh"
    ["swebenchpro"]="swebenchpro_3config.sh"
    ["k8s_docs"]="k8s_docs_3config.sh"
    ["tac"]="tac_3config.sh"
    ["locobench"]="locobench_3config.sh"
    ["largerepo"]="largerepo_3config.sh"
    ["crossrepo"]="crossrepo_3config.sh"
    ["repoqa"]="repoqa_3config.sh"
    ["linuxflbench"]="linuxflbench_3config.sh"
    ["dibench"]="dibench_3config.sh"
    ["sweperf"]="sweperf_3config.sh"
    ["investigation"]="investigation_3config.sh"
    ["dependeval"]="dependeval_3config.sh"
)

# Default order: fastest/cheapest first, most expensive last
DEFAULT_ORDER="codereview repoqa crossrepo k8s_docs sweperf tac largerepo linuxflbench pytorch dibench locobench swebenchpro investigation dependeval"

# ============================================
# PARSE ARGUMENTS
# ============================================
BENCHMARKS=""
CONFIG_FLAGS=""
PARALLEL_OVERRIDE=""
DRY_RUN=false
RESUME_FROM=""
USE_CANARY=true

while [[ $# -gt 0 ]]; do
    case $1 in
        --benchmarks)
            BENCHMARKS="$2"
            shift 2
            ;;
        --configs)
            CONFIG_FLAGS="$2"
            shift 2
            ;;
        --parallel)
            PARALLEL_OVERRIDE="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --resume-from)
            RESUME_FROM="$2"
            shift 2
            ;;
        --no-canary)
            USE_CANARY=false
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Resolve benchmark list
if [ -z "$BENCHMARKS" ]; then
    BENCHMARKS="$DEFAULT_ORDER"
fi

# Build config flag string for 3config scripts
CONFIG_ARG=""
case "$CONFIG_FLAGS" in
    *baseline-only*) CONFIG_ARG="--baseline-only" ;;
    *base-only*)     CONFIG_ARG="--base-only" ;;
    *full-only*)     CONFIG_ARG="--full-only" ;;
    *)               CONFIG_ARG="" ;;  # run all 3 configs
esac

# ============================================
# PRE-FLIGHT
# ============================================
echo "=============================================="
echo "Overnight Benchmark Orchestrator"
echo "=============================================="
echo "Started: $(date)"
echo "Benchmarks: $BENCHMARKS"
echo "Config filter: ${CONFIG_FLAGS:-all}"
echo "Canary: $USE_CANARY"
echo "Dry run: $DRY_RUN"
echo ""

if [ "$DRY_RUN" = false ]; then
    # Set up accounts and refresh tokens
    setup_multi_accounts
    if ! check_token_health; then
        echo ""
        echo "FATAL: Token health check failed before starting. Run:"
        echo "  python3 scripts/headless_login.py --all-accounts"
        exit 1
    fi
fi

# ============================================
# MAIN LOOP
# ============================================
declare -A RESULTS
completed=0
failed=0
skipped=0
blocked=0
resuming=true

if [ -z "$RESUME_FROM" ]; then
    resuming=false
fi

for benchmark in $BENCHMARKS; do
    # Resume-from logic
    if [ "$resuming" = true ]; then
        if [ "$benchmark" = "$RESUME_FROM" ]; then
            resuming=false
        else
            echo "[SKIP] $benchmark (before --resume-from $RESUME_FROM)"
            RESULTS[$benchmark]="skipped"
            skipped=$((skipped + 1))
            continue
        fi
    fi

    script="${BENCHMARK_SCRIPTS[$benchmark]:-}"
    if [ -z "$script" ]; then
        echo "[ERROR] Unknown benchmark: $benchmark"
        RESULTS[$benchmark]="unknown"
        failed=$((failed + 1))
        continue
    fi

    echo ""
    echo "=============================================="
    echo "BENCHMARK: $benchmark"
    echo "Script: $script"
    echo "Time: $(date)"
    echo "=============================================="

    if [ "$DRY_RUN" = true ]; then
        local_args="$CONFIG_ARG"
        [ -n "$PARALLEL_OVERRIDE" ] && local_args="$local_args --parallel $PARALLEL_OVERRIDE"
        echo "[DRY RUN] Would run: CANARY_ENABLED=$USE_CANARY $SCRIPT_DIR/$script $local_args"
        RESULTS[$benchmark]="dry_run"
        continue
    fi

    # Token health check between benchmarks
    if ! check_token_health; then
        echo ""
        echo "BLOCKED: Token health check failed before $benchmark"
        echo "Remaining benchmarks will be skipped."
        RESULTS[$benchmark]="blocked_auth"
        blocked=$((blocked + 1))
        # Mark all remaining as blocked
        for remaining in $BENCHMARKS; do
            if [ -z "${RESULTS[$remaining]:-}" ]; then
                RESULTS[$remaining]="blocked_auth"
                blocked=$((blocked + 1))
            fi
        done
        break
    fi

    # Build command
    cmd="CANARY_ENABLED=$USE_CANARY"
    cmd="$cmd $SCRIPT_DIR/$script"
    [ -n "$CONFIG_ARG" ] && cmd="$cmd $CONFIG_ARG"
    [ -n "$PARALLEL_OVERRIDE" ] && cmd="$cmd --parallel $PARALLEL_OVERRIDE"

    # Run the benchmark
    local_exit=0
    eval "$cmd" || local_exit=$?

    if [ "$local_exit" -eq 0 ]; then
        echo ""
        echo "[DONE] $benchmark completed successfully"
        RESULTS[$benchmark]="completed"
        completed=$((completed + 1))
    else
        echo ""
        echo "[FAIL] $benchmark exited with code $local_exit"
        RESULTS[$benchmark]="failed($local_exit)"
        failed=$((failed + 1))
    fi
done

# ============================================
# SUMMARY
# ============================================
echo ""
echo "=============================================="
echo "Overnight Run Summary"
echo "=============================================="
echo "Finished: $(date)"
echo ""
printf "  %-20s %s\n" "Benchmark" "Result"
printf "  %-20s %s\n" "--------------------" "----------"
for benchmark in $BENCHMARKS; do
    result="${RESULTS[$benchmark]:-not_run}"
    printf "  %-20s %s\n" "$benchmark" "$result"
done
echo ""
echo "Completed: $completed | Failed: $failed | Skipped: $skipped | Blocked: $blocked"
echo ""
