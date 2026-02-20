#!/bin/bash
# Artifact-only evaluation: ccb_test suite (baseline + artifact_full).
#
# Baseline: full local repo, no MCP. Agent produces artifact.
# Artifact-full: empty workspace + Sourcegraph MCP. Agent produces artifact.
# Verifier scores artifact applied to clean /repo_full copy.
#
# Usage:
#   ./configs/test_artifact_2config.sh [--baseline-only|--full-only] [--task TASK_ID] [--parallel N]

export SDLC_SUITE="ccb_test"
export SDLC_SUITE_LABEL="Test (Artifact-Only)"
export FULL_CONFIG="artifact_full"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/sdlc_suite_2config.sh" "$@"
