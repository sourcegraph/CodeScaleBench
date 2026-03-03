#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

export HARBOR_ENV=daytona
export DAYTONA_OVERRIDE_STORAGE=10240

LOG_DIR="$ROOT_DIR/logs/flagged_reruns_20260303"
mkdir -p "$LOG_DIR"

run_wave() {
  local name="$1"
  shift
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] START $name"
  "$@" < <(yes '' | head -n 100) | tee "$LOG_DIR/${name}.log"
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] END   $name"
}

# Remaining mapped waves.
run_wave "mapped_direct_paired_wave2" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/flagged_direct_paired_wave2.json

run_wave "mapped_direct_baseline_only_wave1" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/flagged_direct_baseline_only_wave1.json \
  --baseline-only

run_wave "mapped_direct_baseline_only_wave2" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/flagged_direct_baseline_only_wave2.json \
  --baseline-only

run_wave "mapped_direct_baseline_only_wave3" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/flagged_direct_baseline_only_wave3.json \
  --baseline-only

run_wave "mapped_direct_full_only_wave1" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/flagged_direct_full_only_wave1.json \
  --full-only

run_wave "mapped_direct_full_only_wave2" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/flagged_direct_full_only_wave2.json \
  --full-only

run_wave "mapped_direct_full_only_wave3" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/flagged_direct_full_only_wave3.json \
  --full-only

# Unmapped resolved waves.
run_wave "unmapped_direct_paired_wave1" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/unmapped_direct_paired_wave1.json

run_wave "unmapped_direct_paired_wave2" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/unmapped_direct_paired_wave2.json

run_wave "unmapped_direct_baseline_only_wave1" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/unmapped_direct_baseline_only_wave1.json \
  --baseline-only

run_wave "unmapped_direct_baseline_only_wave2" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/unmapped_direct_baseline_only_wave2.json \
  --baseline-only

run_wave "unmapped_direct_baseline_only_wave3" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/unmapped_direct_baseline_only_wave3.json \
  --baseline-only

run_wave "unmapped_direct_full_only_wave1" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/unmapped_direct_full_only_wave1.json \
  --full-only

run_wave "unmapped_direct_full_only_wave2" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/unmapped_direct_full_only_wave2.json \
  --full-only

run_wave "unmapped_direct_full_only_wave3" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/unmapped_direct_full_only_wave3.json \
  --full-only

run_wave "unmapped_artifact_baseline_only_wave1" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/unmapped_artifact_baseline_only_wave1.json \
  --full-config mcp-remote-artifact \
  --baseline-only

run_wave "unmapped_artifact_baseline_only_wave2" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/unmapped_artifact_baseline_only_wave2.json \
  --full-config mcp-remote-artifact \
  --baseline-only

run_wave "unmapped_artifact_baseline_only_wave3" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/unmapped_artifact_baseline_only_wave3.json \
  --full-config mcp-remote-artifact \
  --baseline-only

