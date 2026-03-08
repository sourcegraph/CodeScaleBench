#!/bin/bash
# Launch full 275-task benchmark with Sonnet 4.6
#
# Two sequential runs:
#   1. Claude Code agent (baseline + MCP pairs)
#   2. OpenHands agent (baseline + MCP pairs)
#
# Each run: 62 task pairs × 2 configs = 124 concurrent Daytona sandboxes
# Total: 275 tasks × 2 configs × 2 agents = 1100 sandbox launches
#
# Usage:
#   ./scripts/launch_sonnet46_benchmark.sh                    # Both agents
#   ./scripts/launch_sonnet46_benchmark.sh --claude-only      # Claude Code only
#   ./scripts/launch_sonnet46_benchmark.sh --openhands-only   # OpenHands only
#   ./scripts/launch_sonnet46_benchmark.sh --dry-run          # Validate without running

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
cd "$REPO_ROOT"

# Defaults
RUN_CLAUDE=true
RUN_OPENHANDS=true
DRY_RUN=""
MODEL="anthropic/claude-sonnet-4-6"
CATEGORY="staging"

while [[ $# -gt 0 ]]; do
    case $1 in
        --claude-only)    RUN_OPENHANDS=false; shift ;;
        --openhands-only) RUN_CLAUDE=false; shift ;;
        --dry-run)        DRY_RUN="--dry-run"; shift ;;
        --category)       CATEGORY="$2"; shift 2 ;;
        *)                echo "Unknown: $1"; exit 1 ;;
    esac
done

# Environment setup
source .env.local 2>/dev/null || true
export HARBOR_ENV=daytona
export DAYTONA_OVERRIDE_STORAGE=10240
export CSB_SKIP_CONFIRM=1

echo "=============================================="
echo "CodeScaleBench Full Benchmark — Sonnet 4.6"
echo "=============================================="
echo "Model: $MODEL"
echo "Tasks: 275 (131 SDLC + 144 Org)"
echo "Configs: baseline-local-direct + mcp-remote-direct"
echo "Environment: Daytona (62 pairs = 124 concurrent sandboxes)"
echo "Category: $CATEGORY"
echo "Claude Code: $RUN_CLAUDE"
echo "OpenHands: $RUN_OPENHANDS"
echo "Dry run: ${DRY_RUN:-no}"
echo ""

# ─────────────────────────────────────────────
# Run 1: Claude Code
# ─────────────────────────────────────────────
if [ "$RUN_CLAUDE" = true ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Phase 1: Claude Code + Sonnet 4.6"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    bash configs/run_selected_tasks.sh \
        --model "$MODEL" \
        --category "$CATEGORY" \
        --skip-prebuild \
        $DRY_RUN

    echo ""
    echo "Claude Code run complete."
    echo ""
fi

# ─────────────────────────────────────────────
# Run 2: OpenHands
# ─────────────────────────────────────────────
if [ "$RUN_OPENHANDS" = true ]; then
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "Phase 2: OpenHands + Sonnet 4.6"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    if [ -n "$DRY_RUN" ]; then
        echo "[DRY RUN] Would launch OpenHands with 275 tasks × 2 configs on Daytona"
        echo "[DRY RUN] Command: bash configs/openhands_2config.sh --model $MODEL --category $CATEGORY"
    else
        bash configs/openhands_2config.sh \
            --model "$MODEL" \
            --category "$CATEGORY"
    fi

    echo ""
    echo "OpenHands run complete."
    echo ""
fi

echo "=============================================="
echo "All benchmark runs finished."
echo "Results in: runs/$CATEGORY/"
echo "=============================================="
