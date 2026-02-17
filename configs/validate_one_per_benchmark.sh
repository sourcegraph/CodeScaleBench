#!/bin/bash
# Validation Runner — one task per benchmark (parallel)
#
# Modes:
#   1) Default: baseline harbor run smoke (uses agent/model)
#   2) --smoke-runtime: no-agent runtime smoke via validate_tasks_preflight.py
#
# Usage:
#   bash configs/validate_one_per_benchmark.sh [--dry-run]
#   bash configs/validate_one_per_benchmark.sh --smoke-runtime [--smoke-timeout-sec 300] [--dry-run]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
cd "$REPO_ROOT"

# Agent module lives in the evals repo; add it to PYTHONPATH
AGENT_DIR="${AGENT_DIR:-$HOME/evals/custom_agents/agents/claudecode}"
export PYTHONPATH="${AGENT_DIR}:$(pwd):${PYTHONPATH:-}"

SELECTION_FILE="$REPO_ROOT/configs/selected_benchmark_tasks.json"
MODEL="${MODEL:-anthropic/claude-opus-4-6}"
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

DRY_RUN=false
SMOKE_RUNTIME=false
SMOKE_TIMEOUT_SEC=300
SMOKE_TIMEOUT_OVERRIDES="${SMOKE_TIMEOUT_OVERRIDES:-ccb_pytorch=900,ccb_tac=900,ccb_crossrepo=900}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --smoke-runtime)
            SMOKE_RUNTIME=true
            shift
            ;;
        --smoke-timeout-sec)
            SMOKE_TIMEOUT_SEC="${2:-}"
            shift 2
            ;;
        --smoke-timeout-overrides)
            SMOKE_TIMEOUT_OVERRIDES="${2:-}"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

if [ "$SMOKE_RUNTIME" = true ]; then
    JOBS_DIR="runs/validation/smoke_runtime_${TIMESTAMP}"
else
    JOBS_DIR="runs/validation/smoke_${TIMESTAMP}"
fi

# Load credentials only for agent-based mode
if [ "$SMOKE_RUNTIME" = false ]; then
    if [ -f ~/evals/.env.local ]; then
        source ~/evals/.env.local
    fi
    if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
        echo "ERROR: ANTHROPIC_API_KEY is not set"
        exit 1
    fi
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
if [ "$SMOKE_RUNTIME" = true ]; then
    echo "Mode:    runtime smoke (no agent)"
    echo "Timeout: ${SMOKE_TIMEOUT_SEC}s per task"
    echo "Overrides: ${SMOKE_TIMEOUT_OVERRIDES:-<none>}"
else
    echo "Mode:    baseline harbor run (no MCP)"
    echo "Model:   $MODEL"
fi
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
        TASK_TIMEOUT="$SMOKE_TIMEOUT_SEC"
        if [ "$SMOKE_RUNTIME" = true ] && [ -n "${SMOKE_TIMEOUT_OVERRIDES:-}" ]; then
            IFS=',' read -ra __OVR_ARR <<< "$SMOKE_TIMEOUT_OVERRIDES"
            for __pair in "${__OVR_ARR[@]}"; do
                __k="${__pair%%=*}"
                __v="${__pair#*=}"
                if [ "$__k" = "$bm" ] && [ -n "$__v" ]; then
                    TASK_TIMEOUT="$__v"
                    break
                fi
            done
        fi
        if [ -d "$path" ] && [ -f "$path/task.toml" ]; then
            echo "  OK   $path"
            if [ "$SMOKE_RUNTIME" = true ]; then
                echo "      cmd: python3 scripts/validate_tasks_preflight.py --task $path --smoke-runtime --smoke-timeout-sec $TASK_TIMEOUT --format json"
            else
                echo "      cmd: BASELINE_MCP_TYPE=none harbor run --path $path --agent-import-path $AGENT_PATH --model $MODEL ..."
            fi
        else
            echo "  FAIL $path"
        fi
    done
    exit 0
fi

mkdir -p "$JOBS_DIR"

PIDS=()
BMS=()
declare -A PATH_BY_BM

for line in "${TASK_LINES[@]}"; do
    IFS=$'\t' read -r bm path <<< "$line"
    abs_path="$REPO_ROOT/$path"
    PATH_BY_BM["$bm"]="$abs_path"

    if [ ! -d "$abs_path" ]; then
        echo "SKIP: $bm — directory not found: $abs_path"
        continue
    fi

    if [ "$SMOKE_RUNTIME" = true ]; then
        TASK_TIMEOUT="$SMOKE_TIMEOUT_SEC"
        if [ -n "${SMOKE_TIMEOUT_OVERRIDES:-}" ]; then
            IFS=',' read -ra __OVR_ARR <<< "$SMOKE_TIMEOUT_OVERRIDES"
            for __pair in "${__OVR_ARR[@]}"; do
                __k="${__pair%%=*}"
                __v="${__pair#*=}"
                if [ "$__k" = "$bm" ] && [ -n "$__v" ]; then
                    TASK_TIMEOUT="$__v"
                    break
                fi
            done
        fi
        echo "Launching runtime smoke: $bm ($path)"
        python3 scripts/validate_tasks_preflight.py \
            --task "$abs_path" \
            --smoke-runtime \
            --smoke-timeout-sec "$TASK_TIMEOUT" \
            --format json \
            > "$JOBS_DIR/${bm}.log" 2>&1 &
    else
        echo "Launching harbor smoke: $bm ($path)"
        BASELINE_MCP_TYPE=none harbor run \
            --path "$abs_path" \
            --agent-import-path "$AGENT_PATH" \
            --model "$MODEL" \
            --jobs-dir "$JOBS_DIR/$bm" \
            -n 1 \
            --timeout-multiplier 10 \
            > "$JOBS_DIR/${bm}.log" 2>&1 &
    fi

    PIDS+=($!)
    BMS+=("$bm")
done

echo ""
echo "All ${#PIDS[@]} tasks launched. Waiting for completion..."
echo ""

declare -A EXIT_CODES
for i in "${!PIDS[@]}"; do
    wait "${PIDS[$i]}" 2>/dev/null || true
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
    if [ "$SMOKE_RUNTIME" = true ]; then
        log="$JOBS_DIR/${bm}.log"
        if [ ! -f "$log" ]; then
            printf "  %-25s FAILED (missing log)\n" "$bm"
            FAIL=$((FAIL + 1))
            continue
        fi
        if python3 - "$log" <<'PYEOF' >/dev/null 2>&1
import json,sys
from pathlib import Path
txt = Path(sys.argv[1]).read_text(errors="replace")
start = txt.find("{")
if start < 0:
    raise SystemExit(2)
data = json.loads(txt[start:])
raise SystemExit(0 if data.get("critical", 1) == 0 else 1)
PYEOF
        then
            printf "  %-25s SMOKE_OK\n" "$bm"
            PASS=$((PASS + 1))
        else
            summary=$(python3 - "$log" <<'PYEOF'
import json,sys
from pathlib import Path
txt = Path(sys.argv[1]).read_text(errors="replace")
start = txt.find("{")
if start < 0:
    print("non-json output")
    raise SystemExit(0)
data = json.loads(txt[start:])
print(f"critical={data.get('critical', '?')} warning={data.get('warning','?')} issues={data.get('total_issues','?')}")
PYEOF
)
            printf "  %-25s FAILED: %s\n" "$bm" "$summary"
            FAIL=$((FAIL + 1))
        fi
    else
        reward_file=$(find "$JOBS_DIR/$bm" -name reward.txt 2>/dev/null | head -1 || true)
        if [ -n "$reward_file" ]; then
            reward=$(cat "$reward_file")
            printf "  %-25s reward=%s\n" "$bm" "$reward"
            PASS=$((PASS + 1))
        else
            printf "  %-25s FAILED (exit=%s, check %s.log)\n" "$bm" "${EXIT_CODES[$bm]}" "$bm"
            FAIL=$((FAIL + 1))
        fi
    fi
done

echo ""
echo "Summary: $PASS passed, $FAIL failed out of ${#BMS[@]} benchmarks"
echo "Logs:    $JOBS_DIR/*.log"
