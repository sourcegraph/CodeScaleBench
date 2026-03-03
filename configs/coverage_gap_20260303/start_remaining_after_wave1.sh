#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

LOG_DIR="$ROOT_DIR/logs/flagged_reruns_20260303"
mkdir -p "$LOG_DIR"

TARGET='run_selected_tasks.sh --selection-file configs/coverage_gap_20260303/flagged_direct_paired_wave1.json'

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] waiting for active wave1 processes to finish..." | tee -a "$LOG_DIR/remaining_unmapped_nohup.out"
while pgrep -af "$TARGET" >/dev/null; do
  sleep 30
done

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] wave1 finished, starting remaining+unmapped runner..." | tee -a "$LOG_DIR/remaining_unmapped_nohup.out"
exec "$ROOT_DIR/configs/coverage_gap_20260303/run_daytona_remaining_and_unmapped.sh" >> "$LOG_DIR/remaining_unmapped_nohup.out" 2>&1

