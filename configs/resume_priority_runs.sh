#!/bin/bash
# Resume script for priority benchmark runs after VM spin-down.
#
# What happened: swebenchpro baseline got 4/36 tasks done before the VM died.
# This script:
#   1. Finishes the remaining 32 swebenchpro baseline tasks (same jobs dir)
#   2. Extracts metrics for the entire swebenchpro baseline batch
#   3. Runs swebenchpro --full-only (fresh)
#   4. Runs crossrepo --baseline-only (fresh)
#   5. Runs crossrepo --full-only (fresh)
#   6. Runs locobench --baseline-only (fresh)
#   7. Runs locobench --full-only (fresh)
#
# Launch in tmux:
#   tmux new-session -d -s ccb './configs/resume_priority_runs.sh 2>&1 | tee runs/official/resume.log'
#   tmux attach -t ccb

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

# Agent module
AGENT_DIR="${AGENT_DIR:-$HOME/evals/custom_agents/agents/claudecode}"
export PYTHONPATH="${AGENT_DIR}:$(pwd):$PYTHONPATH"

# Load credentials
if [ -f ~/evals/.env.local ]; then
    source ~/evals/.env.local
fi

if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ERROR: ANTHROPIC_API_KEY is not set"
    exit 1
fi

SELECTION_FILE="$SCRIPT_DIR/selected_benchmark_tasks.json"
AGENT_PATH="agents.claude_baseline_agent:BaselineClaudeCodeAgent"
MODEL="${MODEL:-anthropic/claude-opus-4-5-20251101}"
CONCURRENCY=2
TIMEOUT_MULTIPLIER=10

# Existing swebenchpro baseline jobs dir to resume into
SWEBENCH_JOBS_BASE="runs/official/swebenchpro_selected_opus_20260202_024115"

# Extract per-task metrics helper
extract_all_metrics() {
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

echo "=============================================="
echo "Resuming Priority Benchmark Runs"
echo "=============================================="
echo "Start time: $(date)"
echo ""

# ============================================
# STEP 1: Finish swebenchpro baseline (remaining tasks)
# ============================================
echo ""
echo "[1/7] Resuming swebenchpro baseline (skipping already-completed tasks)..."
echo ""

# Dynamically detect completed tasks from existing result.json files
REMAINING_TASK_ARGS=$(python3 -c "
import json, os

completed_ids = set()
basedir = os.path.expanduser('$SWEBENCH_JOBS_BASE/baseline')
if os.path.isdir(basedir):
    for batch in os.listdir(basedir):
        batchdir = os.path.join(basedir, batch)
        if not os.path.isdir(batchdir):
            continue
        for task in os.listdir(batchdir):
            rj = os.path.join(batchdir, task, 'result.json')
            if os.path.isfile(rj):
                try:
                    data = json.load(open(rj))
                    tid = data.get('task_name', '')
                    if tid:
                        completed_ids.add(tid)
                except: pass

tasks = json.load(open('$SELECTION_FILE'))['tasks']
remaining = [t['task_id'] for t in tasks if t['benchmark'] == 'ccb_swebenchpro' and t['task_id'] not in completed_ids]
import sys
print(f'Completed: {len(completed_ids)}, Remaining: {len(remaining)}', file=sys.stderr)
for tid in remaining:
    print(f'-t {tid}')
")

if [ -z "$REMAINING_TASK_ARGS" ]; then
    echo "All swebenchpro baseline tasks already completed!"
else
    BASELINE_MCP_TYPE=none harbor run \
        --dataset swebenchpro \
        ${REMAINING_TASK_ARGS} \
        --agent-import-path "${AGENT_PATH}" \
        --model "${MODEL}" \
        --jobs-dir "${SWEBENCH_JOBS_BASE}/baseline" \
        -n ${CONCURRENCY} \
        --timeout-multiplier ${TIMEOUT_MULTIPLIER} \
        2>&1 | tee "${SWEBENCH_JOBS_BASE}/baseline_resume.log"
fi

extract_all_metrics "${SWEBENCH_JOBS_BASE}/baseline" "ccb_swebenchpro" "baseline"

echo "[1/7] swebenchpro baseline DONE at $(date)"

# ============================================
# STEP 2: swebenchpro full (fresh run)
# ============================================
echo ""
echo "[2/7] Starting swebenchpro full..."
echo ""

./configs/swebenchpro_3config.sh --full-only
echo "[2/7] swebenchpro full DONE at $(date)"

# ============================================
# STEP 3: crossrepo baseline
# ============================================
echo ""
echo "[3/7] Starting crossrepo baseline..."
echo ""

./configs/crossrepo_3config.sh --baseline-only
echo "[3/7] crossrepo baseline DONE at $(date)"

# ============================================
# STEP 4: crossrepo full
# ============================================
echo ""
echo "[4/7] Starting crossrepo full..."
echo ""

./configs/crossrepo_3config.sh --full-only
echo "[4/7] crossrepo full DONE at $(date)"

# ============================================
# STEP 5: locobench baseline
# ============================================
echo ""
echo "[5/7] Starting locobench baseline..."
echo ""

./configs/locobench_3config.sh --baseline-only
echo "[5/7] locobench baseline DONE at $(date)"

# ============================================
# STEP 6: locobench full
# ============================================
echo ""
echo "[6/7] Starting locobench full..."
echo ""

./configs/locobench_3config.sh --full-only
echo "[6/7] locobench full DONE at $(date)"

# ============================================
# STEP 7: Extract metrics for the original 4 completed tasks
# ============================================
echo ""
echo "[7/7] Extracting metrics for originally completed tasks..."
extract_all_metrics "${SWEBENCH_JOBS_BASE}/baseline" "ccb_swebenchpro" "baseline"

echo ""
echo "=============================================="
echo "All Priority Runs Complete!"
echo "=============================================="
echo "End time: $(date)"
echo ""
echo "Results:"
echo "  ls runs/official/"
