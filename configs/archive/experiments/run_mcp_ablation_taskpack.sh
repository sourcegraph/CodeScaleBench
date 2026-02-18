#!/bin/bash
# Run a curated MCP ablation task pack into runs/experimental
# Default: paired baseline + sourcegraph_full on the same tasks.
# With --with-sgonly: also runs an "sg_only_env" arm — same sourcegraph_full
# agent, but Dockerfile.sg_only swapped in so the container has no local source.
#
# sg_only_env mode is purely an environment modification:
#   - Swaps Dockerfile -> Dockerfile.sg_only (no repo clone).
#   - Sets BASELINE_MCP_TYPE=sourcegraph_full (same agent behaviour).
#   - Tasks without Dockerfile.sg_only are SKIPPED for this arm.

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
RUN_SGONLY=false
TIMEOUT_MULTIPLIER="${TIMEOUT_MULTIPLIER:-10}"
RUN_ID="${RUN_ID:-mcp_ablation_v1_$(date +%Y%m%d_%H%M%S)}"
JOBS_BASE="runs/${CATEGORY}/${RUN_ID}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --baseline-only)
      RUN_FULL=false
      RUN_SGONLY=false
      shift
      ;;
    --full-only)
      RUN_BASELINE=false
      RUN_SGONLY=false
      shift
      ;;
    --sgonly-only)
      RUN_BASELINE=false
      RUN_FULL=false
      RUN_SGONLY=true
      shift
      ;;
    --with-sgonly)
      RUN_SGONLY=true
      shift
      ;;
    --no-baseline)
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

NEEDS_SG_TOKEN=false
if [ "$RUN_FULL" = true ] || [ "$RUN_SGONLY" = true ]; then
  NEEDS_SG_TOKEN=true
fi
if [ "$NEEDS_SG_TOKEN" = true ] && [ -z "${SOURCEGRAPH_ACCESS_TOKEN:-}" ]; then
  echo "ERROR: SOURCEGRAPH_ACCESS_TOKEN is required for sourcegraph_full / sg_only_env"
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
echo "Configs:     baseline=$RUN_BASELINE sourcegraph_full=$RUN_FULL sg_only_env=$RUN_SGONLY"
echo ""

# ============================================
# Dockerfile swap helpers for SG-only mode
# ============================================
swap_to_sgonly() {
  local task_dir="$1"
  local dockerfile="benchmarks/${task_dir}/environment/Dockerfile"
  local sgonly="benchmarks/${task_dir}/environment/Dockerfile.sg_only"
  local backup="benchmarks/${task_dir}/environment/Dockerfile.original"

  if [ ! -f "$sgonly" ]; then
    return 1
  fi

  if [ ! -f "$backup" ]; then
    cp "$dockerfile" "$backup"
  fi
  cp "$sgonly" "$dockerfile"
  return 0
}

restore_dockerfile() {
  local task_dir="$1"
  local dockerfile="benchmarks/${task_dir}/environment/Dockerfile"
  local backup="benchmarks/${task_dir}/environment/Dockerfile.original"

  if [ -f "$backup" ]; then
    mv "$backup" "$dockerfile"
  fi
}

# ============================================
# Run one task in a given mode
# ============================================
run_one() {
  local task_dir="$1"
  local mode="$2"       # baseline | sourcegraph_full | sg_only_env
  local repo_name="$3"

  # sg_only_env uses the same agent MCP type as sourcegraph_full;
  # the only difference is the Dockerfile (already swapped by caller).
  if [ "$mode" = "sourcegraph_full" ] || [ "$mode" = "sg_only_env" ]; then
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

# ============================================
# Parse task list from JSON
# ============================================
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

  # SG-only env: swap Dockerfile to the .sg_only variant.
  sgonly_swapped=false
  sgonly_skip=false
  if [ "$RUN_SGONLY" = true ]; then
    if swap_to_sgonly "$tdir"; then
      echo "  [sg_only_env] Swapped Dockerfile -> Dockerfile.sg_only"
      sgonly_swapped=true
    else
      echo "  [sg_only_env] WARNING: No Dockerfile.sg_only for ${tid} — skipping sg_only_env arm"
      sgonly_skip=true
    fi
  fi

  base_pid=""
  full_pid=""
  sgonly_pid=""

  if [ "$RUN_BASELINE" = true ]; then
    echo "  Mode: baseline (paired launch)"
    run_one "$tdir" "baseline" "$repo" &
    base_pid=$!
  fi

  if [ "$RUN_FULL" = true ]; then
    echo "  Mode: sourcegraph_full (paired launch)"
    run_one "$tdir" "sourcegraph_full" "$repo" &
    full_pid=$!
  fi

  if [ "$RUN_SGONLY" = true ] && [ "$sgonly_skip" = false ]; then
    echo "  Mode: sg_only_env (paired launch)"
    run_one "$tdir" "sg_only_env" "$repo" &
    sgonly_pid=$!
  fi

  base_rc=0
  full_rc=0
  sgonly_rc=0
  if [ -n "$base_pid" ]; then
    wait "$base_pid" || base_rc=$?
  fi
  if [ -n "$full_pid" ]; then
    wait "$full_pid" || full_rc=$?
  fi
  if [ -n "$sgonly_pid" ]; then
    wait "$sgonly_pid" || sgonly_rc=$?
  fi

  # Restore original Dockerfile before error check (always clean up)
  if [ "$sgonly_swapped" = true ]; then
    restore_dockerfile "$tdir"
    echo "  [sg_only_env] Restored original Dockerfile"
  fi

  if [ "$base_rc" -ne 0 ] || [ "$full_rc" -ne 0 ] || [ "$sgonly_rc" -ne 0 ]; then
    echo "ERROR: Paired run failed for task ${tid} (baseline_rc=${base_rc}, full_rc=${full_rc}, sgonly_rc=${sgonly_rc})"
    echo "  Continuing to next task..."
  fi
done < /tmp/mcp_ablation_tasks.tsv

echo ""
echo "Done. Results: $JOBS_BASE"
echo "Suggested post-run checks:"
echo "  python3 scripts/generate_manifest.py"
echo "  python3 scripts/compare_configs.py --format json --paired-analysis"
echo "  python3 scripts/mcp_audit.py --all-runs --json --verbose"
