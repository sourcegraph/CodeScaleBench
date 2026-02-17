#!/bin/bash
# Run a curated MCP ablation task pack into runs/experimental
# Default: paired baseline + sourcegraph_full on the same tasks.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

AGENT_DIR="${AGENT_DIR:-$HOME/evals/custom_agents/agents/claudecode}"
export PYTHONPATH="${AGENT_DIR}:$(pwd):${PYTHONPATH:-}"

source "$REPO_ROOT/configs/_common.sh"

TASK_FILE="${TASK_FILE:-$REPO_ROOT/configs/experiments/mcp_ablation_taskpack_v1.json}"
MODEL="${MODEL:-anthropic/claude-opus-4-6}"
CATEGORY="${CATEGORY:-experimental}"
RUN_BASELINE=true
RUN_FULL=true
TIMEOUT_MULTIPLIER="${TIMEOUT_MULTIPLIER:-10}"
RUN_ID="${RUN_ID:-mcp_ablation_v1_$(date +%Y%m%d_%H%M%S)}"
JOBS_BASE="runs/${CATEGORY}/${RUN_ID}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --baseline-only)
      RUN_FULL=false
      shift
      ;;
    --full-only)
      RUN_BASELINE=false
      shift
      ;;
    --task-file)
      TASK_FILE="$2"
      shift 2
      ;;
    --model)
      MODEL="$2"
      shift 2
      ;;
    --category)
      CATEGORY="$2"
      JOBS_BASE="runs/${CATEGORY}/${RUN_ID}"
      shift 2
      ;;
    --run-id)
      RUN_ID="$2"
      JOBS_BASE="runs/${CATEGORY}/${RUN_ID}"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

if [ ! -f "$TASK_FILE" ]; then
  echo "ERROR: task file not found: $TASK_FILE"
  exit 1
fi

if [ -f ~/evals/.env.local ]; then
  source ~/evals/.env.local
fi

enforce_subscription_mode
setup_dual_accounts
ACTIVE_CLAUDE_HOME="${ACTIVE_CLAUDE_HOME:-${CLAUDE_HOMES[0]}}"
if [ -z "${ACTIVE_CLAUDE_HOME:-}" ] || [ ! -f "$ACTIVE_CLAUDE_HOME/.claude/.credentials.json" ]; then
  echo "ERROR: No valid ACTIVE_CLAUDE_HOME found (got: ${ACTIVE_CLAUDE_HOME:-<empty>})"
  exit 1
fi

if [ "$RUN_FULL" = true ] && [ -z "${SOURCEGRAPH_ACCESS_TOKEN:-}" ]; then
  echo "ERROR: SOURCEGRAPH_ACCESS_TOKEN is required for sourcegraph_full"
  exit 1
fi

ensure_fresh_token_all
mkdir -p "$JOBS_BASE"

echo "=============================================="
echo "MCP Ablation Task Pack Runner"
echo "=============================================="
echo "Task file:   $TASK_FILE"
echo "Model:       $MODEL"
echo "Category:    $CATEGORY"
echo "Run ID:      $RUN_ID"
echo "Jobs base:   $JOBS_BASE"
echo "Configs:     baseline=$RUN_BASELINE sourcegraph_full=$RUN_FULL"
echo ""

run_one() {
  local task_dir="$1"
  local mode="$2"
  local repo_name="$3"

  if [ "$mode" = "sourcegraph_full" ]; then
    export BASELINE_MCP_TYPE=sourcegraph_full
    if [ -n "$repo_name" ]; then
      export SOURCEGRAPH_REPO_NAME="$repo_name"
    else
      unset SOURCEGRAPH_REPO_NAME || true
    fi
  else
    export BASELINE_MCP_TYPE=none
    unset SOURCEGRAPH_REPO_NAME || true
  fi

  HOME="$ACTIVE_CLAUDE_HOME" harbor run \
    --path "benchmarks/${task_dir}" \
    --agent-import-path "agents.claude_baseline_agent:BaselineClaudeCodeAgent" \
    --model "$MODEL" \
    --jobs-dir "$JOBS_BASE/$mode" \
    --timeout-multiplier "$TIMEOUT_MULTIPLIER" \
    -n 1
}

python3 - <<'PY' "$TASK_FILE" > /tmp/mcp_ablation_tasks.tsv
import json,sys
j=json.load(open(sys.argv[1]))
for t in j['tasks']:
    repo=t.get('repo','') or ''
    print(f"{t['benchmark']}\t{t['task_id']}\t{t['task_dir']}\t{repo}")
PY

while IFS=$'\t' read -r bm tid tdir repo; do
  echo "----------------------------------------------"
  echo "Task: ${tid} (${bm})"
  echo "Dir:  benchmarks/${tdir}"

  ensure_fresh_token_all

  base_pid=""
  full_pid=""

  if [ "$RUN_BASELINE" = true ]; then
    echo "Mode: baseline (paired launch)"
    run_one "$tdir" "baseline" "$repo" &
    base_pid=$!
  fi

  if [ "$RUN_FULL" = true ]; then
    echo "Mode: sourcegraph_full (paired launch)"
    run_one "$tdir" "sourcegraph_full" "$repo" &
    full_pid=$!
  fi

  base_rc=0
  full_rc=0
  if [ -n "$base_pid" ]; then
    wait "$base_pid" || base_rc=$?
  fi
  if [ -n "$full_pid" ]; then
    wait "$full_pid" || full_rc=$?
  fi

  if [ "$base_rc" -ne 0 ] || [ "$full_rc" -ne 0 ]; then
    echo "ERROR: Paired run failed for task ${tid} (baseline_rc=${base_rc}, sourcegraph_full_rc=${full_rc})"
    exit 1
  fi
done < /tmp/mcp_ablation_tasks.tsv

echo ""
echo "Done. Results: $JOBS_BASE"
echo "Suggested post-run checks:"
echo "  python3 scripts/generate_manifest.py"
echo "  python3 scripts/compare_configs.py --format json --paired-analysis"
echo "  python3 scripts/mcp_audit.py --all-runs --json --verbose"
