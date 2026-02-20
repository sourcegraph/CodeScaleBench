#!/usr/bin/env bash
# Ralph runner (headless/non-interactive).
# Usage: ./ralph.sh [--tool amp|claude] [max_iterations]

set -euo pipefail

TOOL="claude"
MAX_ITERATIONS=10
TIMEOUT_SEC="${RALPH_TIMEOUT_SEC:-900}"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [--tool amp|claude] [--timeout-sec N] [max_iterations]

Runs the selected tool in headless mode from this Ralph instance directory.
Examples:
  ./ralph-sdlc-suite-reorg/ralph.sh --tool claude --timeout-sec 600 1
  ./ralph-sdlc-suite-reorg/ralph.sh 5
USAGE
}

ts() { date '+%Y-%m-%d %H:%M:%S %Z'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tool)
      TOOL="${2:-}"
      shift 2
      ;;
    --tool=*)
      TOOL="${1#*=}"
      shift
      ;;
    --timeout-sec)
      TIMEOUT_SEC="${2:-}"
      shift 2
      ;;
    --timeout-sec=*)
      TIMEOUT_SEC="${1#*=}"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      if [[ "$1" =~ ^[0-9]+$ ]]; then
        MAX_ITERATIONS="$1"
        shift
      else
        echo "Error: unknown argument '$1'" >&2
        usage
        exit 1
      fi
      ;;
  esac
done

if [[ "$TOOL" != "claude" && "$TOOL" != "amp" ]]; then
  echo "Error: Invalid tool '$TOOL'. Must be 'claude' or 'amp'." >&2
  exit 1
fi
if ! [[ "$TIMEOUT_SEC" =~ ^[0-9]+$ ]] || [[ "$TIMEOUT_SEC" -le 0 ]]; then
  echo "Error: --timeout-sec must be a positive integer." >&2
  exit 1
fi

INSTANCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$INSTANCE_DIR"

PRD_FILE="$INSTANCE_DIR/prd.json"
PROGRESS_FILE="$INSTANCE_DIR/progress.txt"
RUN_LOG="$INSTANCE_DIR/ralph-run.log"
ARCHIVE_DIR="$INSTANCE_DIR/archive"
LAST_BRANCH_FILE="$INSTANCE_DIR/.last-branch"

for req in CLAUDE.md AGENTS.md "$PRD_FILE" "$PROGRESS_FILE"; do
  if [[ ! -f "$req" ]]; then
    echo "Error: missing required file in $INSTANCE_DIR: $req" >&2
    exit 1
  fi
done

if ! command -v "$TOOL" >/dev/null 2>&1; then
  echo "Error: tool '$TOOL' is not installed or not on PATH" >&2
  exit 127
fi

CURRENT_BRANCH="$(jq -r '.branchName // empty' "$PRD_FILE" 2>/dev/null || true)"
if [[ -f "$LAST_BRANCH_FILE" ]]; then
  LAST_BRANCH="$(cat "$LAST_BRANCH_FILE" 2>/dev/null || true)"
else
  LAST_BRANCH=""
fi

if [[ -n "$CURRENT_BRANCH" && -n "$LAST_BRANCH" && "$CURRENT_BRANCH" != "$LAST_BRANCH" ]]; then
  DATE_PREFIX="$(date +%Y-%m-%d)"
  SAFE_BRANCH="${LAST_BRANCH#ralph/}"
  DEST="$ARCHIVE_DIR/${DATE_PREFIX}-${SAFE_BRANCH}"
  mkdir -p "$DEST"
  [[ -f "$PRD_FILE" ]] && cp "$PRD_FILE" "$DEST/prd.json"
  [[ -f "$PROGRESS_FILE" ]] && cp "$PROGRESS_FILE" "$DEST/progress.txt"
  [[ -f "$RUN_LOG" ]] && cp "$RUN_LOG" "$DEST/ralph-run.log"
  echo "[$(ts)] Archived previous run to $DEST" | tee -a "$PROGRESS_FILE" "$RUN_LOG"
fi

if [[ -n "$CURRENT_BRANCH" ]]; then
  echo "$CURRENT_BRANCH" > "$LAST_BRANCH_FILE"
fi

touch "$RUN_LOG"

echo "Starting Ralph - Tool: $TOOL - Max iterations: $MAX_ITERATIONS - Timeout: ${TIMEOUT_SEC}s" | tee -a "$RUN_LOG"
echo "[$(ts)] Ralph start | tool=$TOOL | max_iterations=$MAX_ITERATIONS | timeout_sec=$TIMEOUT_SEC" >> "$PROGRESS_FILE"

for i in $(seq 1 "$MAX_ITERATIONS"); do
  ITER_HEADER="Ralph Iteration $i of $MAX_ITERATIONS ($TOOL)"
  {
    echo ""
    echo "==============================================================="
    echo "  $ITER_HEADER"
    echo "==============================================================="
  } | tee -a "$RUN_LOG"
  echo "[$(ts)] Iteration $i started" >> "$PROGRESS_FILE"

  if command -v timeout >/dev/null 2>&1; then
    set +e
    if [[ "$TOOL" == "amp" ]]; then
      OUTPUT="$(timeout "$TIMEOUT_SEC" bash -lc 'cat CLAUDE.md | amp --dangerously-allow-all' 2>&1 | tee -a "$RUN_LOG")"
    else
      OUTPUT="$(timeout "$TIMEOUT_SEC" bash -lc 'claude --dangerously-skip-permissions --print < CLAUDE.md' 2>&1 | tee -a "$RUN_LOG")"
    fi
    CMD_STATUS=$?
    set -e
    if [[ "$CMD_STATUS" -eq 124 ]]; then
      echo "[$(ts)] Iteration $i timed out after ${TIMEOUT_SEC}s" | tee -a "$RUN_LOG" >> "$PROGRESS_FILE"
      exit 124
    fi
  else
    if [[ "$TOOL" == "amp" ]]; then
      OUTPUT="$(cat CLAUDE.md | amp --dangerously-allow-all 2>&1 | tee -a "$RUN_LOG")" || true
    else
      OUTPUT="$(claude --dangerously-skip-permissions --print < CLAUDE.md 2>&1 | tee -a "$RUN_LOG")" || true
    fi
  fi

  STORY_MARKERS="$(echo "$OUTPUT" | grep -oE '<story id="US-[0-9]{3}" status="(done|blocked|in_progress)">[^<]*</story>' || true)"
  if [[ -n "$STORY_MARKERS" ]]; then
    echo "[$(ts)] Iteration $i story markers:" >> "$PROGRESS_FILE"
    echo "$STORY_MARKERS" >> "$PROGRESS_FILE"
  else
    echo "[$(ts)] Iteration $i no story markers found" >> "$PROGRESS_FILE"
  fi

  if echo "$OUTPUT" | grep -q '<promise>COMPLETE</promise>'; then
    echo "" | tee -a "$RUN_LOG"
    echo "Ralph completed all tasks." | tee -a "$RUN_LOG"
    echo "Completed at iteration $i of $MAX_ITERATIONS" | tee -a "$RUN_LOG"
    echo "[$(ts)] COMPLETE marker detected at iteration $i" >> "$PROGRESS_FILE"
    exit 0
  fi

  echo "Iteration $i complete. Continuing..." | tee -a "$RUN_LOG"
  echo "[$(ts)] Iteration $i complete" >> "$PROGRESS_FILE"
  sleep 2
done

echo "" | tee -a "$RUN_LOG"
echo "Ralph reached max iterations ($MAX_ITERATIONS) without COMPLETE signal." | tee -a "$RUN_LOG"
echo "Check $PROGRESS_FILE and $RUN_LOG for status." | tee -a "$RUN_LOG"
echo "[$(ts)] Max iterations reached without COMPLETE" >> "$PROGRESS_FILE"
exit 1
