#!/usr/bin/env python3
"""Sync oracle_answer.json files -> task_spec.json required_files for new MCP tasks.

Unlike hydrate_task_specs.py, this ONLY updates artifacts.oracle.required_files
and does NOT touch evaluation.checks (preserves existing search_pattern).

Usage:
    python3 scripts/sync_oracle_files.py [--dry-run] [--min-id N] [--max-id N]
"""

import argparse
import json
import glob
import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCHMARKS_DIR = os.path.join(PROJECT_ROOT, "benchmarks")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--min-id", type=int, default=142)
    parser.add_argument("--max-id", type=int, default=9999)
    args = parser.parse_args()

    oracle_files = sorted(glob.glob(
        os.path.join(BENCHMARKS_DIR, "ccb_mcp_*/*/tests/oracle_answer.json")
    ))

    ok = skip_empty = skip_missing = 0
    for oracle_path in oracle_files:
        parts = oracle_path.split(os.sep)
        task_id = parts[-3]
        m = re.search(r"-(\d+)$", task_id)
        if not m:
            continue
        num = int(m.group(1))
        if not (args.min_id <= num <= args.max_id):
            continue

        spec_path = os.path.join(os.path.dirname(oracle_path), "task_spec.json")
        if not os.path.isfile(spec_path):
            print(f"SKIP {task_id}: no task_spec.json")
            skip_missing += 1
            continue

        oracle = json.load(open(oracle_path))
        files = oracle.get("files", [])
        if not files:
            print(f"SKIP {task_id}: oracle has no files")
            skip_empty += 1
            continue

        spec = json.load(open(spec_path))
        spec.setdefault("artifacts", {}).setdefault("oracle", {})["required_files"] = files

        if args.dry_run:
            print(f"DRY-RUN {task_id}: would set {len(files)} required_files")
        else:
            with open(spec_path, "w") as f:
                json.dump(spec, f, indent=2)
                f.write("\n")
            print(f"OK {task_id}: set {len(files)} required_files")
        ok += 1

    print(f"\nDone: {ok} updated, {skip_empty} skipped (empty oracle), {skip_missing} skipped (missing spec)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
