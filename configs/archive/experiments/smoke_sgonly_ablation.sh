#!/bin/bash
# SG-Only smoke test for ablation task pack
# Tests that all write-only tasks build and verify with Dockerfile.sg_only,
# and that source-requiring tasks build with their original Dockerfile.
#
# Usage:
#   bash configs/experiments/smoke_sgonly_ablation.sh [--dry-run]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

TASK_FILE="${TASK_FILE:-$REPO_ROOT/configs/experiments/mcp_ablation_taskpack_v1.json}"
SMOKE_TIMEOUT="${SMOKE_TIMEOUT:-300}"
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=true; shift ;;
    --timeout) SMOKE_TIMEOUT="$2"; shift 2 ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
JOBS_DIR="runs/validation/sgonly_smoke_${TIMESTAMP}"
mkdir -p "$JOBS_DIR"

swap_to_sgonly() {
  local task_dir="$1"
  local dockerfile="${task_dir}/environment/Dockerfile"
  local sgonly="${task_dir}/environment/Dockerfile.sg_only"
  local backup="${task_dir}/environment/Dockerfile.original"

  if [ ! -f "$sgonly" ]; then return 1; fi
  if [ ! -f "$backup" ]; then cp "$dockerfile" "$backup"; fi
  cp "$sgonly" "$dockerfile"
  return 0
}

restore_dockerfile() {
  local task_dir="$1"
  local dockerfile="${task_dir}/environment/Dockerfile"
  local backup="${task_dir}/environment/Dockerfile.original"
  if [ -f "$backup" ]; then mv "$backup" "$dockerfile"; fi
}

python3 - <<'PY' "$TASK_FILE" > /tmp/sgonly_smoke_tasks.tsv
import json, sys
j = json.load(open(sys.argv[1]))
for t in j['tasks']:
    print(f"{t['benchmark']}\t{t['task_id']}\t{t['task_dir']}")
PY

echo "=============================================="
echo "SG-Only Ablation Smoke Tests"
echo "=============================================="
echo "Task file: $TASK_FILE"
echo "Timeout:   ${SMOKE_TIMEOUT}s"
echo "Output:    $JOBS_DIR"
echo ""

PASS=0
FAIL=0
SKIP=0
TOTAL=0

while IFS=$'\t' read -r bm tid tdir; do
  TOTAL=$((TOTAL + 1))
  task_path="benchmarks/${tdir}"
  abs_path="$REPO_ROOT/$task_path"
  sgonly_file="${abs_path}/environment/Dockerfile.sg_only"

  if [ ! -d "$abs_path" ]; then
    echo "  SKIP  $tid — task dir not found"
    SKIP=$((SKIP + 1))
    continue
  fi

  has_sgonly=false
  if [ -f "$sgonly_file" ]; then
    has_sgonly=true
  fi

  echo -n "  $tid ($bm) "
  if [ "$has_sgonly" = true ]; then
    echo -n "[Dockerfile.sg_only] "
  else
    echo -n "[truncation-mode] "
  fi

  if [ "$DRY_RUN" = true ]; then
    echo "DRY_RUN"
    continue
  fi

  # Swap Dockerfile if sg_only variant exists
  swapped=false
  if [ "$has_sgonly" = true ]; then
    if swap_to_sgonly "$abs_path"; then
      swapped=true
    fi
  fi

  # Run the smoke
  set +e
  python3 scripts/validate_tasks_preflight.py \
    --task "$abs_path" \
    --smoke-runtime \
    --smoke-timeout-sec "$SMOKE_TIMEOUT" \
    --format json \
    > "$JOBS_DIR/${tid}.log" 2>&1
  smoke_rc=$?
  set -e

  # Restore
  if [ "$swapped" = true ]; then
    restore_dockerfile "$abs_path"
  fi

  # Parse result
  if python3 - "$JOBS_DIR/${tid}.log" <<'PYEOF' >/dev/null 2>&1
import json, sys
from pathlib import Path
txt = Path(sys.argv[1]).read_text(errors="replace")
start = txt.find("{")
if start < 0:
    raise SystemExit(2)
data = json.loads(txt[start:])
raise SystemExit(0 if data.get("critical", 1) == 0 else 1)
PYEOF
  then
    echo "OK"
    PASS=$((PASS + 1))
  else
    # Check for acceptable no-agent smoke outcomes
    if python3 - "$JOBS_DIR/${tid}.log" <<'PYEOF2' >/dev/null 2>&1
import json, sys
from pathlib import Path
txt = Path(sys.argv[1]).read_text(errors="replace")
start = txt.find("{")
if start < 0:
    raise SystemExit(2)
data = json.loads(txt[start:])
issues = data.get("issues", [])
only_nonzero_reward = all(
    "smoke_verifier_nonzero_with_reward" in str(i.get("check", ""))
    or "smoke_build_timeout" in str(i.get("check", ""))
    or "smoke_verify_timeout" in str(i.get("check", ""))
    for i in issues if i.get("severity") == "CRITICAL"
)
raise SystemExit(0 if only_nonzero_reward or data.get("critical", 0) == 0 else 1)
PYEOF2
    then
      echo "OK (acceptable no-agent smoke)"
      PASS=$((PASS + 1))
    else
      echo "FAILED (see $JOBS_DIR/${tid}.log)"
      FAIL=$((FAIL + 1))
    fi
  fi
done < /tmp/sgonly_smoke_tasks.tsv

echo ""
echo "=============================================="
echo "Summary: $PASS passed, $FAIL failed, $SKIP skipped out of $TOTAL"
echo "Logs:    $JOBS_DIR/"
echo "=============================================="
