#!/usr/bin/env python3
"""Generate deterministic SDLC-quality test.sh for promoted Org->SDLC tasks.

Reads configs/org_promotion_manifest.json and generates a new test.sh for
each of the 67 promoted tasks. The generated test.sh:
  - Is self-contained (no eval.sh indirection)
  - Runs oracle_checks via promoted_verifier.py with suite-specific weights
  - Outputs detailed validation_result.json
  - Has multiple assertion patterns (per-check thresholds)
  - Follows SDLC conventions (sg_only guard, reward.txt, exit-code-first)

Usage:
    python3 scripts/generate_promoted_verifiers.py [--dry-run] [--force]

Flags:
    --dry-run   Print what would be generated without writing files
    --force     Overwrite existing test.sh even if it differs from the template
"""

import argparse
import json
import os
import shutil
import stat
import sys
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "configs" / "org_promotion_manifest.json"
PROMOTED_VERIFIER_SRC = ROOT / "scripts" / "promoted_verifier.py"

# Template for the generated test.sh — uses $-style substitution to avoid
# conflicts with bash ${} and Python {} in inline code.
TEST_SH_TEMPLATE = Template(r'''#!/bin/bash
# test.sh — Deterministic SDLC verifier for $task_id
# Promoted from $from_suite -> $target_suite
#
# Reward: suite-weighted composite (0.0-1.0) via oracle file/symbol/chain/keyword F1
# Multiple assertion patterns: file_set_match + symbol_resolution + keyword_presence
#   [+ dependency_chain where oracle defines chains]
#
# Scoring weights ($target_suite):
#   See promoted_verifier.py SUITE_WEIGHTS for per-check weight allocation.

# sg_only mode guard: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

# NOTE: set -e intentionally NOT used — fallback logic requires graceful failure handling
set -uo pipefail

TASK_ID="$task_id"
TARGET_SUITE="$target_suite"
ANSWER_PATH="/workspace/answer.json"
TASK_SPEC_PATH="/tests/task_spec.json"
PROMOTED_VERIFIER="/tests/promoted_verifier.py"
ORACLE_CHECKS="/tests/oracle_checks.py"
REWARD_PATH="/logs/verifier/reward.txt"
VALIDATION_RESULT="/logs/verifier/validation_result.json"

mkdir -p /logs/verifier

echo "=== $$TASK_ID deterministic verifier ===" >&2
echo "Suite: $$TARGET_SUITE (promoted from $from_suite)" >&2
echo "" >&2

# ------------------------------------------------------------------
# Assertion 1: answer.json exists
# ------------------------------------------------------------------
if [ ! -f "$$ANSWER_PATH" ]; then
    echo "FAIL: answer.json not found at $$ANSWER_PATH" >&2
    echo "0.0" > "$$REWARD_PATH"
    echo '{"composite_score": 0.0, "error": "answer.json not found"}' > "$$VALIDATION_RESULT"
    exit 1
fi
echo "PASS: answer.json exists" >&2

# ------------------------------------------------------------------
# Assertion 2: answer.json is valid JSON with expected structure
# ------------------------------------------------------------------
STRUCT_CHECK=$$(python3 << 'PYEOF'
import json, sys
try:
    with open("/workspace/answer.json") as f:
        data = json.load(f)
except (json.JSONDecodeError, OSError) as e:
    print(f"invalid JSON: {e}", file=sys.stderr)
    sys.exit(1)
if not isinstance(data, dict):
    print("answer.json is not a JSON object", file=sys.stderr)
    sys.exit(1)
keys = set(data.keys())
expected = {"files", "symbols", "text", "chain", "dependency_chain", "answer"}
if not keys & expected:
    print(f"answer.json missing expected keys (has: {keys})", file=sys.stderr)
    sys.exit(1)
print("ok")
PYEOF
) 2>&1

if [ "$$STRUCT_CHECK" != "ok" ]; then
    echo "FAIL: answer.json structure check: $$STRUCT_CHECK" >&2
    echo "0.0" > "$$REWARD_PATH"
    echo '{"composite_score": 0.0, "error": "answer.json invalid structure"}' > "$$VALIDATION_RESULT"
    exit 1
fi
echo "PASS: answer.json is valid JSON with expected structure" >&2

# ------------------------------------------------------------------
# Assertion 3: oracle data available
# ------------------------------------------------------------------
if [ ! -f "$$TASK_SPEC_PATH" ]; then
    echo "FAIL: task_spec.json not found" >&2
    echo "0.0" > "$$REWARD_PATH"
    exit 1
fi
if [ ! -f "$$ORACLE_CHECKS" ]; then
    echo "FAIL: oracle_checks.py not found" >&2
    echo "0.0" > "$$REWARD_PATH"
    exit 1
fi
echo "PASS: oracle data and checker available" >&2

# ------------------------------------------------------------------
# Assertion 4+: Run suite-weighted oracle checks
# ------------------------------------------------------------------
echo "" >&2
echo "Running suite-weighted oracle checks ($$TARGET_SUITE)..." >&2

if [ -f "$$PROMOTED_VERIFIER" ]; then
    # Use promoted_verifier.py for suite-specific weights
    SCORE=$$(python3 "$$PROMOTED_VERIFIER" \
        --answer "$$ANSWER_PATH" \
        --spec "$$TASK_SPEC_PATH" \
        --suite "$$TARGET_SUITE" \
        --output "$$VALIDATION_RESULT" \
        --verbose 2>&1 | tee /dev/stderr | tail -1) || true
else
    # Fallback: use oracle_checks.py directly (equal weights)
    echo "WARNING: promoted_verifier.py not found, using oracle_checks.py directly" >&2
    SCORE=$$(python3 "$$ORACLE_CHECKS" \
        --answer "$$ANSWER_PATH" \
        --spec "$$TASK_SPEC_PATH" \
        --verbose 2>&1 | tee /dev/stderr | tail -1) || true
fi

# ------------------------------------------------------------------
# Validate and write reward
# ------------------------------------------------------------------
if ! echo "$$SCORE" | python3 -c "import sys; float(sys.stdin.read().strip())" 2>/dev/null; then
    echo "FAIL: verifier did not return a valid score: $$SCORE" >&2
    echo "0.0" > "$$REWARD_PATH"
    exit 1
fi

echo "" >&2
echo "Composite score: $$SCORE" >&2
echo "$$SCORE" > "$$REWARD_PATH"

# ------------------------------------------------------------------
# Per-check assertion summary (if validation_result.json exists)
# ------------------------------------------------------------------
if [ -f "$$VALIDATION_RESULT" ]; then
    python3 << 'PYEOF2' >&2 || true
import json, sys
result = json.load(open("/logs/verifier/validation_result.json"))
per_check = result.get("per_check", {})
print("")
print("Per-check assertions:")
for check_type, info in per_check.items():
    score = info.get("score", 0)
    weight = info.get("weight", 0)
    status = "PASS" if score > 0 else "FAIL"
    print(f"  {status}: {check_type} = {score:.4f} (weight={weight:.2f})")
PYEOF2
fi

echo "" >&2
echo "Reward: $$SCORE" >&2

# Exit-code-first (SWE-Factory pattern)
python3 -c "import sys; sys.exit(0 if float('$$SCORE') > 0 else 1)"
''')


def find_task_dir(task_id: str, from_suite: str) -> Path | None:
    """Find the actual directory for a task (handles case variants)."""
    suite_dir = ROOT / "benchmarks" / from_suite
    for variant in [task_id, task_id.lower(), task_id.upper()]:
        candidate = suite_dir / variant
        if candidate.is_dir():
            return candidate
    return None


def generate_test_sh(task: dict, dry_run: bool = False, force: bool = False) -> str:
    """Generate test.sh for a single promoted task. Returns status message."""
    task_id = task["task_id"]
    from_suite = task["from_suite"]
    target_suite = task["target_suite"]

    task_dir = find_task_dir(task_id, from_suite)
    if task_dir is None:
        return f"SKIP {task_id}: directory not found in {from_suite}"

    tests_dir = task_dir / "tests"
    test_sh = tests_dir / "test.sh"
    verifier_dst = tests_dir / "promoted_verifier.py"

    # Generate test.sh content
    content = TEST_SH_TEMPLATE.substitute(
        task_id=task_id,
        target_suite=target_suite,
        from_suite=from_suite,
    )

    if dry_run:
        return f"DRY-RUN {task_id}: would write {test_sh} ({len(content)} bytes)"

    # Back up existing test.sh
    if test_sh.exists():
        backup = tests_dir / "test.sh.org_backup"
        if not backup.exists():
            shutil.copy2(test_sh, backup)

    # Write test.sh
    with open(test_sh, "w") as f:
        f.write(content)
    os.chmod(test_sh, os.stat(test_sh).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # Copy promoted_verifier.py into tests/
    if PROMOTED_VERIFIER_SRC.exists():
        shutil.copy2(PROMOTED_VERIFIER_SRC, verifier_dst)

    return f"OK {task_id}: {test_sh}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print without writing")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    args = parser.parse_args()

    if not MANIFEST_PATH.exists():
        print(f"ERROR: manifest not found at {MANIFEST_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)

    tasks = manifest["tasks"]
    print(f"Processing {len(tasks)} promoted tasks...")

    by_suite: dict[str, int] = {}
    ok_count = 0

    for task in tasks:
        status = generate_test_sh(task, dry_run=args.dry_run, force=args.force)
        print(f"  {status}")
        if status.startswith("OK"):
            ok_count += 1
            suite = task["target_suite"]
            by_suite[suite] = by_suite.get(suite, 0) + 1

    print(f"\nDone: {ok_count}/{len(tasks)} tasks processed")
    if by_suite:
        print("By target suite:")
        for suite, count in sorted(by_suite.items()):
            print(f"  {suite}: {count}")


if __name__ == "__main__":
    main()
