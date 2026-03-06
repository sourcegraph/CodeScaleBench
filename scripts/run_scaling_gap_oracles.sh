#!/usr/bin/env bash
# Run Daytona curator on the 12 new scaling-gap Org tasks
# These had manually curated (incorrect) oracle_answer.json files
set -euo pipefail

source .env.local
export DAYTONA_OVERRIDE_STORAGE=10240

TASK_DIRS=(
  benchmarks/csb_org_compliance/ccx-compliance-286
  benchmarks/csb_org_compliance/ccx-compliance-292
  benchmarks/csb_org_crossorg/ccx-crossorg-288
  benchmarks/csb_org_crossorg/ccx-crossorg-295
  benchmarks/csb_org_crossrepo_tracing/ccx-dep-trace-293
  benchmarks/csb_org_migration/ccx-migration-289
  benchmarks/csb_org_migration/ccx-migration-294
  benchmarks/csb_org_org/ccx-agentic-290
  benchmarks/csb_org_platform/ccx-platform-285
  benchmarks/csb_org_platform/ccx-platform-291
  benchmarks/csb_org_security/ccx-vuln-remed-287
  benchmarks/csb_org_security/ccx-vuln-remed-296
)

LOG="/tmp/curator_scaling_gap_$(date +%Y%m%d_%H%M%S).log"
echo "Logging to $LOG"
echo "Starting curator batch: ${#TASK_DIRS[@]} tasks" | tee "$LOG"

PASSED=0
FAILED=0

for td in "${TASK_DIRS[@]}"; do
  task_name=$(basename "$td")
  echo "=== [$((PASSED + FAILED + 1))/${#TASK_DIRS[@]}] $task_name ===" | tee -a "$LOG"

  if python3 scripts/daytona_curator_runner.py \
    --task-dir "$td" \
    --overwrite-existing \
    --model claude-opus-4-6 \
    --prompt-version phase1 \
    --backend hybrid \
    --verbose 2>&1 | tee -a "$LOG"; then
    echo "OK: $task_name" | tee -a "$LOG"
    PASSED=$((PASSED + 1))
  else
    echo "FAIL: $task_name" | tee -a "$LOG"
    FAILED=$((FAILED + 1))
  fi
done

echo ""
echo "=== SUMMARY ===" | tee -a "$LOG"
echo "Passed: $PASSED / ${#TASK_DIRS[@]}" | tee -a "$LOG"
echo "Failed: $FAILED / ${#TASK_DIRS[@]}" | tee -a "$LOG"
echo "Log: $LOG"
