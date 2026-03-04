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
  set +o pipefail
  "$@" 2>&1 | tee "$LOG_DIR/${name}.log"
  local rc=${PIPESTATUS[0]}
  set -o pipefail
  if [ "$rc" -ne 0 ]; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] FAIL  $name (exit=$rc)"
    return "$rc"
  fi
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] END   $name"
}

run_wave "vm_recovery_paired_20260303" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/vm_recovery_paired_no_openlibrary_20260303.json

run_wave "vm_recovery_baseline_only_20260303" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/vm_recovery_baseline_only_20260303.json \
  --baseline-only

run_wave "vm_recovery_mcp_only_20260303" \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/vm_recovery_mcp_only_20260303.json \
  --full-only
