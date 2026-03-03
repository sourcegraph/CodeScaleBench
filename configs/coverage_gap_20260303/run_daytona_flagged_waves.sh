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

run_wave "direct_paired_wave1" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/flagged_direct_paired_wave1.json

run_wave "direct_paired_wave2" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/flagged_direct_paired_wave2.json

run_wave "direct_baseline_only_wave1" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/flagged_direct_baseline_only_wave1.json \
  --baseline-only

run_wave "direct_baseline_only_wave2" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/flagged_direct_baseline_only_wave2.json \
  --baseline-only

run_wave "direct_baseline_only_wave3" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/flagged_direct_baseline_only_wave3.json \
  --baseline-only

run_wave "direct_full_only_wave1" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/flagged_direct_full_only_wave1.json \
  --full-only

run_wave "direct_full_only_wave2" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/flagged_direct_full_only_wave2.json \
  --full-only

run_wave "direct_full_only_wave3" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/flagged_direct_full_only_wave3.json \
  --full-only
