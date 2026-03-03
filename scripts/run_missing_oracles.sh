#!/bin/bash
# Run the curator agent on all 77 missing SDLC tasks using the phase1 prompt.
#
# Usage:
#   bash scripts/run_missing_oracles.sh              # Full run (77 tasks)
#   bash scripts/run_missing_oracles.sh --dry-run     # Preview only
#   bash scripts/run_missing_oracles.sh --max-tasks 5  # Pilot run
#
# The phase1 prompt (from commit af296756c) scored F1=0.749 on 10-task pilot,
# significantly outperforming the V7/V8 edit-centric prompts (F1=0.39-0.44).
#
# Estimated cost: ~$38 (77 tasks x ~$0.50/task with Opus)
# Estimated time: ~2-3 hours sequential, ~30min with Daytona parallelism

set -euo pipefail
cd "$(dirname "$0")/.."

# Source credentials
if [ -f .env.local ]; then
    source .env.local
fi

# Verify SG token
if [ -z "${SOURCEGRAPH_ACCESS_TOKEN:-}" ]; then
    echo "WARNING: SOURCEGRAPH_ACCESS_TOKEN not set. Hybrid backend will fall back to local-only."
    echo "  Set it in .env.local or export SOURCEGRAPH_ACCESS_TOKEN=..."
fi

echo "=== Running curator on missing SDLC ground truth tasks ==="
echo "Prompt: phase1 (recall-focused)"
echo "Model: claude-opus-4-6"
echo "Backend: hybrid"
echo ""

python3 scripts/context_retrieval_agent.py \
    --sdlc-all \
    --missing-only \
    --backend hybrid \
    --model claude-opus-4-6 \
    --prompt-version phase1 \
    --no-verify \
    --overwrite-existing \
    --verbose \
    "$@"
