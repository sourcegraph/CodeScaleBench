#!/usr/bin/env bash
set -euo pipefail

HARBOR_ENV=daytona DAYTONA_OVERRIDE_STORAGE=10240 \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/selected_rerun_interrupted_vm_baseline.json \
  --benchmark csb_sdlc_fix \
  --baseline-only \
  --skip-prebuild

HARBOR_ENV=daytona DAYTONA_OVERRIDE_STORAGE=10240 \
  ./configs/run_selected_tasks.sh \
  --selection-file configs/selected_rerun_interrupted_vm_full.json \
  --benchmark csb_sdlc_fix \
  --full-only \
  --skip-prebuild
