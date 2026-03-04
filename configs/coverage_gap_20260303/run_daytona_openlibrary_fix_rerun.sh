#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

export HARBOR_ENV=daytona
export DAYTONA_OVERRIDE_STORAGE=10240

LOG_DIR="$ROOT_DIR/logs/flagged_reruns_20260303"
mkdir -p "$LOG_DIR"

name="openlibrary_fix_rerun_20260303"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] START $name"
set +o pipefail
./configs/run_selected_tasks.sh \
  --selection-file configs/coverage_gap_20260303/openlibrary_solr_boolean_fix_rerun_20260303.json \
  <<< "" 2>&1 | tee "$LOG_DIR/${name}.log"
cmd_status=${PIPESTATUS[0]}
set -o pipefail
if [ "$cmd_status" -ne 0 ]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] FAIL  $name (exit=$cmd_status)"
  exit "$cmd_status"
fi
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] END   $name"
