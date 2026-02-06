#!/usr/bin/env python3
"""
Migrate result.json files from rewards.score to rewards.reward.

Scans runs/official/ for task-level result.json files that use
'score' instead of 'reward' inside the rewards dict, renames the key,
and creates .bak backups.
"""

import json
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "runs" / "official"


def main():
    if not RUNS_DIR.exists():
        print(f"ERROR: {RUNS_DIR} not found", file=sys.stderr)
        sys.exit(1)

    migrated = 0
    skipped = 0
    errors = 0

    for result_path in sorted(RUNS_DIR.rglob("result.json")):
        try:
            data = json.loads(result_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            print(f"ERROR: {result_path}: {e}", file=sys.stderr)
            errors += 1
            continue

        # Skip batch-level results (no task_name)
        if "task_name" not in data:
            continue

        verifier_result = data.get("verifier_result") or {}
        rewards = verifier_result.get("rewards") or {}

        if "score" not in rewards or "reward" in rewards:
            skipped += 1
            continue

        # Migrate: rename score -> reward
        backup_path = result_path.with_suffix(".json.bak")
        shutil.copy2(result_path, backup_path)

        rewards["reward"] = rewards.pop("score")
        result_path.write_text(json.dumps(data, indent=2) + "\n")
        migrated += 1
        print(f"MIGRATED  {result_path.relative_to(RUNS_DIR)}")

    print(f"\nMigrated {migrated} files, skipped {skipped} files (already compliant)")
    if errors:
        print(f"Errors: {errors}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
