#!/bin/bash
# Launch all SDLC suites on local Docker with 3 variance passes.
# Usage: bash configs/run_all_sdlc_local.sh [--passes N] [--suites "suite1 suite2 ..."]
#
# Defaults: 3 passes, all 8 SDLC suites (excluding ccb_fix which already has 3 runs).
# Runs sequentially — each suite finishes before the next starts.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# Load credentials
if [ -f .env.local ]; then
    set -a; source .env.local; set +a
fi

PASSES=${PASSES:-3}
SUITES="${SUITES:-debug design document feature refactor secure test understand}"

# Parse args
while [[ $# -gt 0 ]]; do
    case $1 in
        --passes) PASSES="$2"; shift 2 ;;
        --suites) SUITES="$2"; shift 2 ;;
        --skip-first-pass-for)
            # Skip specific suites in pass 1 (already have a run in progress)
            SKIP_PASS1="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "=============================================="
echo "LOCAL DOCKER BATCH LAUNCHER"
echo "=============================================="
echo "Suites:  $SUITES"
echo "Passes:  $PASSES"
echo "Skip P1: ${SKIP_PASS1:-none}"
echo ""

TOTAL_SUITES=$(echo $SUITES | wc -w)
TOTAL_RUNS=$((TOTAL_SUITES * PASSES))
echo "Total suite runs: $TOTAL_RUNS ($TOTAL_SUITES suites x $PASSES passes)"
echo "Started at: $(date)"
echo ""
read -r -p "Press Enter to start, Ctrl+C to abort... " _

FAILED=()
COMPLETED=()
LOGDIR="runs/staging/_batch_logs_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOGDIR"

for pass in $(seq 1 $PASSES); do
    echo ""
    echo "========================================"
    echo "VARIANCE PASS $pass / $PASSES ($(date))"
    echo "========================================"

    for suite in $SUITES; do
        # Skip suites in pass 1 if requested
        if [ "$pass" -eq 1 ] && echo "${SKIP_PASS1:-}" | grep -qw "$suite"; then
            echo "--- Skipping ${suite} pass $pass (already running) ---"
            continue
        fi

        echo ""
        echo "--- Pass $pass: ${suite} ($(date)) ---"
        start_time=$(date +%s)
        logfile="${LOGDIR}/${suite}_pass${pass}.log"

        # Pipe empty line for confirm_launch gate, skip prebuild
        if echo '' | bash "$SCRIPT_DIR/${suite}_2config.sh" --no-prebuild 2>&1 | tee "$logfile"; then
            elapsed=$(( $(date +%s) - start_time ))
            echo "COMPLETED: ${suite} pass $pass (${elapsed}s)"
            COMPLETED+=("${suite}_pass${pass}")
        else
            elapsed=$(( $(date +%s) - start_time ))
            echo "FAILED: ${suite} pass $pass (${elapsed}s)"
            FAILED+=("${suite}_pass${pass}")
        fi

        echo "--- Cooling down 10s between suites ---"
        sleep 10
    done
done

echo ""
echo "=============================================="
echo "BATCH COMPLETE ($(date))"
echo "=============================================="
echo "Completed: ${#COMPLETED[@]} / $TOTAL_RUNS"
if [ ${#FAILED[@]} -gt 0 ]; then
    echo "Failed: ${FAILED[*]}"
fi
echo ""
echo "Logs: $LOGDIR"
echo "Runs saved to: runs/staging/"
ls -dt runs/staging/*_haiku_2026030* 2>/dev/null | head -$((TOTAL_RUNS + 5))
