#!/bin/bash
# Run all variance rerun waves sequentially (designed for overnight unattended execution).
# Each wave adds 1 run per task toward the target of 3 runs per config.
#
# Usage:
#   nohup ./configs/run_variance_waves.sh > logs/variance_waves_$(date +%Y%m%d_%H%M%S).log 2>&1 &
#
# To start from a specific wave (e.g., after wave 1 already ran):
#   nohup ./configs/run_variance_waves.sh --start-wave 2 > logs/variance_waves_$(date +%Y%m%d_%H%M%S).log 2>&1 &

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
cd "$REPO_ROOT"

START_STEP=1
while [[ $# -gt 0 ]]; do
    case $1 in
        --start-step) START_STEP="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

WAVE_DIR="configs/variance_reruns"
RUNNER="./configs/run_selected_tasks.sh"
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

STARTED_AT=$(date '+%Y-%m-%d %H:%M:%S')
echo "=============================================="
echo "Variance Rerun — All Waves"
echo "=============================================="
echo "Started:     $STARTED_AT"
echo "Start step:  $START_STEP"
echo ""

# Each entry: wave_num selection_file flags
STEPS=(
    "1 wave1_both.json "
    "1 wave1_baseline_only.json --baseline-only"
    "1 wave1_mcp_only.json --full-only"
    "2 wave2_repoqa.json "
    "2 wave2_remainder.json "
    "2 wave2_baseline_only.json --baseline-only"
    "2 wave2_mcp_only.json --full-only"
    "3 wave3_both.json "
    "3 wave3_baseline_only.json --baseline-only"
)

TOTAL=${#STEPS[@]}
STEP_NUM=0
FAILED=0

for entry in "${STEPS[@]}"; do
    read -r wave_num selection_file flags <<< "$entry"
    STEP_NUM=$((STEP_NUM + 1))

    # Skip steps below start
    if [ "$STEP_NUM" -lt "$START_STEP" ]; then
        echo "[Step $STEP_NUM/$TOTAL] SKIP (step $STEP_NUM < start_step $START_STEP)"
        continue
    fi

    selection_path="${WAVE_DIR}/${selection_file}"
    if [ ! -f "$selection_path" ]; then
        echo "[Step $STEP_NUM/$TOTAL] SKIP — $selection_path not found"
        continue
    fi

    # Check if selection file has any tasks
    task_count=$(python3 -c "import json; print(len(json.load(open('$selection_path')).get('tasks',[])))")
    if [ "$task_count" -eq 0 ]; then
        echo "[Step $STEP_NUM/$TOTAL] SKIP — $selection_file has 0 tasks"
        continue
    fi

    step_log="${LOG_DIR}/wave${wave_num}_${selection_file%.json}_$(date +%Y%m%d_%H%M%S).log"

    echo ""
    echo "=============================================="
    echo "[Step $STEP_NUM/$TOTAL] Wave $wave_num — $selection_file ($task_count tasks) $flags"
    echo "  Log: $step_log"
    echo "  Started: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "=============================================="

    # Pipe newline to auto-confirm the interactive prompt.
    # Tee to both step log and stdout so the wrapper log captures everything.
    if echo "" | $RUNNER \
        --selection-file "$selection_path" \
        --category staging \
        $flags \
        2>&1 | tee "$step_log"; then
        echo "[Step $STEP_NUM/$TOTAL] DONE at $(date '+%Y-%m-%d %H:%M:%S')"
    else
        echo "[Step $STEP_NUM/$TOTAL] FAILED (exit $?) at $(date '+%Y-%m-%d %H:%M:%S')"
        FAILED=$((FAILED + 1))
        # Continue to next step — don't abort the whole overnight run
    fi
done

echo ""
echo "=============================================="
echo "All waves complete"
echo "  Started:  $STARTED_AT"
echo "  Finished: $(date '+%Y-%m-%d %H:%M:%S')"
echo "  Failed steps: $FAILED / $TOTAL"
echo "=============================================="
