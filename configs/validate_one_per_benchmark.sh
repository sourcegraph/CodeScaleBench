#!/bin/bash
# Validation Runner — One task per benchmark, baseline only (parallel)
#
# Runs the first task from each of the 11 benchmarks concurrently to verify
# adapters, Docker images, and result collection are working.
#
# Usage:
#   bash configs/validate_one_per_benchmark.sh [--dry-run]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
cd "$REPO_ROOT"

# Agent module lives in the evals repo; add it to PYTHONPATH
AGENT_DIR="${AGENT_DIR:-$HOME/evals/custom_agents/agents/claudecode}"
export PYTHONPATH="${AGENT_DIR}:$(pwd):$PYTHONPATH"

DRY_RUN=false
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=true
fi

SELECTION_FILE="$REPO_ROOT/configs/selected_benchmark_tasks.json"
MODEL="${MODEL:-anthropic/claude-opus-4-5-20251101}"
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
JOBS_DIR="runs/validation/smoke_${TIMESTAMP}"

# Load credentials
if [ -f ~/evals/.env.local ]; then
    source ~/evals/.env.local
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: ANTHROPIC_API_KEY is not set"
    exit 1
fi

# Extract first task per benchmark into arrays
readarray -t TASK_LINES < <(python3 -c "
import json
sel = json.load(open('$SELECTION_FILE'))
seen = set()
for t in sel['tasks']:
    bm = t['benchmark']
    if bm not in seen:
        seen.add(bm)
        print(f'{bm}\tbenchmarks/{t[\"task_dir\"]}')
")

echo "=============================================="
echo "CodeContextBench Validation Run (parallel)"
echo "=============================================="
echo "Mode:    baseline (no MCP)"
echo "Model:   $MODEL"
echo "Tasks:   1 per benchmark (${#TASK_LINES[@]} total, all concurrent)"
echo "Output:  $JOBS_DIR"
echo ""
echo "Tasks:"
for line in "${TASK_LINES[@]}"; do
    IFS=$'\t' read -r bm path <<< "$line"
    printf "  %-20s %s\n" "$bm" "$path"
done
echo ""

if [ "$DRY_RUN" = true ]; then
    echo "[DRY RUN] Verifying task directories..."
    for line in "${TASK_LINES[@]}"; do
        IFS=$'\t' read -r bm path <<< "$line"
        if [ -d "$path" ] && [ -f "$path/task.toml" ]; then
            echo "  OK   $path"
        else
            echo "  FAIL $path"
        fi
    done
    exit 0
fi

mkdir -p "$JOBS_DIR"

# Launch all tasks in parallel
PIDS=()
BMS=()

for line in "${TASK_LINES[@]}"; do
    IFS=$'\t' read -r bm path <<< "$line"
    abs_path="$REPO_ROOT/$path"

    if [ ! -d "$abs_path" ]; then
        echo "SKIP: $bm — directory not found: $abs_path"
        continue
    fi

    echo "Launching: $bm ($path)"
    BASELINE_MCP_TYPE=none harbor run \
        --path "$abs_path" \
        --agent-import-path "$AGENT_PATH" \
        --model "$MODEL" \
        --jobs-dir "$JOBS_DIR/$bm" \
        -n 1 \
        --timeout-multiplier 10 \
        > "$JOBS_DIR/${bm}.log" 2>&1 &

    PIDS+=($!)
    BMS+=("$bm")
done

echo ""
echo "All ${#PIDS[@]} tasks launched. Waiting for completion..."
echo ""
echo "Monitor progress:"
echo "  watch -n 10 'find $JOBS_DIR -name reward.txt -exec sh -c \"echo \\\$1: \\\$(cat \\\$1)\" _ {} \\;'"
echo ""

# Wait for all and collect exit codes
declare -A EXIT_CODES
for i in "${!PIDS[@]}"; do
    wait "${PIDS[$i]}" 2>/dev/null
    EXIT_CODES["${BMS[$i]}"]=$?
done

echo ""
echo "=============================================="
echo "Validation Complete"
echo "=============================================="
echo ""
echo "Results per benchmark:"
echo ""

PASS=0
FAIL=0

for bm in "${BMS[@]}"; do
    reward_file=$(find "$JOBS_DIR/$bm" -name reward.txt 2>/dev/null | head -1)

    if [ -n "$reward_file" ]; then
        reward=$(cat "$reward_file")
        printf "  %-25s reward=%s\n" "$bm" "$reward"
        PASS=$((PASS + 1))
    else
        # Try to extract error info
        result_file=$(find "$JOBS_DIR/$bm" -name result.json -path "*/2026-*" 2>/dev/null | head -1)
        if [ -n "$result_file" ]; then
            error=$(python3 -c "
import json
try:
    r = json.load(open('$result_file'))
    trials = r.get('trials', [])
    if trials:
        exc = trials[0].get('exception', {})
        if isinstance(exc, dict): print(exc.get('type','') + ': ' + exc.get('message','')[:60])
        elif exc: print(str(exc)[:80])
        else: print('completed (no reward file)')
    else: print('no trials')
except Exception as e: print(f'parse error: {e}')
" 2>/dev/null)
            printf "  %-25s ERROR: %s\n" "$bm" "$error"
        else
            printf "  %-25s FAILED (exit=%s, check %s.log)\n" "$bm" "${EXIT_CODES[$bm]}" "$bm"
        fi
        FAIL=$((FAIL + 1))
    fi
done

echo ""
echo "Summary: $PASS passed, $FAIL failed out of ${#BMS[@]} benchmarks"
echo "Logs:    $JOBS_DIR/*.log"
