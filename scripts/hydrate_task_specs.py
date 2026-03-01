#!/usr/bin/env python3
"""Hydrate task_spec.json oracle fields from oracle_answer.json for MCP-unique tasks.

Reads each task's oracle_answer.json and populates:
  1. artifacts.oracle.required_files   <- oracle_answer["files"]
  2. artifacts.oracle.required_symbols <- oracle_answer["symbols"]
  3. artifacts.oracle.dependency_chains <- [{"steps": oracle_answer["chain"]}]
  4. evaluation.checks array           <- based on oracle_check_types from selection file

Also extracts keyword lists for keyword_presence checks from oracle symbol names.

Usage:
    python3 scripts/hydrate_task_specs.py [--dry-run] [--selection-file PATH]
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BENCHMARKS_DIR = os.path.join(PROJECT_ROOT, "benchmarks")

DEFAULT_SELECTION = os.path.join(
    PROJECT_ROOT, "configs", "selected_mcp_tasks_121_141.json"
)


def load_selection(path: str) -> List[Dict[str, Any]]:
    """Load task selection file and return task list."""
    with open(path) as f:
        data = json.load(f)
    return data["tasks"]


def load_json(path: str) -> Dict[str, Any]:
    """Load a JSON file."""
    with open(path) as f:
        return json.load(f)


def _normalize_file_entry(entry) -> Dict[str, str]:
    """Convert a file entry to {"repo": ..., "path": ...} dict format.

    Handles both dict entries (already correct) and string entries like
    "sg-evals/kubernetes--v1.32.0/pkg/apis/rbac/v1alpha1/file.go" where
    the first two path components are the repo and the rest is the file path.

    Also handles "github.com/sg-evals/repo--hash/path" by stripping the
    "github.com/" prefix first so the repo is "sg-evals/repo--hash".
    """
    if isinstance(entry, dict):
        return entry
    if isinstance(entry, str):
        # Strip github.com/ prefix — oracle entries sometimes include it
        s = entry
        if s.startswith("github.com/"):
            s = s[len("github.com/"):]
        parts = s.split("/", 2)
        if len(parts) >= 3:
            return {"repo": f"{parts[0]}/{parts[1]}", "path": parts[2]}
        elif len(parts) == 2:
            return {"repo": parts[0], "path": parts[1]}
        else:
            return {"repo": "", "path": s}
    return {"repo": "", "path": str(entry)}


def build_checks(oracle_check_types: List[str], oracle_answer: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Build evaluation checks array from oracle_check_types and oracle data."""
    checks = []

    for check_type in oracle_check_types:
        if check_type == "file_set_match":
            checks.append({
                "type": "file_set_match",
                "params": {
                    "search_pattern": "",
                    "file_filter": "",
                },
            })

        elif check_type == "symbol_resolution":
            checks.append({
                "type": "symbol_resolution",
                "params": {},
            })

        elif check_type == "dependency_chain":
            checks.append({
                "type": "dependency_chain",
                "params": {},
            })

        elif check_type == "keyword_presence":
            # Extract unique symbol names as required keywords
            symbols = oracle_answer.get("symbols", [])
            keywords = list(dict.fromkeys(  # dedupe preserving order
                s.get("symbol", "") for s in symbols if s.get("symbol")
            ))
            checks.append({
                "type": "keyword_presence",
                "params": {
                    "required_keywords": keywords,
                },
            })

        elif check_type == "test_ratio":
            checks.append({
                "type": "test_ratio",
                "params": {
                    "test_command": "echo no-test",
                    "workspace_dir": "/workspace",
                },
            })

        else:
            print(f"  WARNING: unknown check type '{check_type}', skipping")

    return checks


def hydrate_task(task_entry: Dict[str, Any], dry_run: bool) -> str:
    """Hydrate one task's task_spec.json from its oracle_answer.json.

    Returns status string.
    """
    task_id = task_entry["task_id"]
    task_dir_rel = task_entry["task_dir"]
    oracle_check_types = task_entry.get("oracle_check_types", [])

    task_dir = os.path.join(BENCHMARKS_DIR, task_dir_rel)

    # Auto-infer check types from oracle data when not specified
    if not oracle_check_types:
        oracle_path_peek = os.path.join(task_dir, "tests", "oracle_answer.json")
        if os.path.isfile(oracle_path_peek):
            peek = load_json(oracle_path_peek)
            if peek.get("files"):
                oracle_check_types.append("file_set_match")
            if peek.get("symbols"):
                oracle_check_types.append("symbol_resolution")
                oracle_check_types.append("keyword_presence")
            if peek.get("chain"):
                oracle_check_types.append("dependency_chain")
    spec_path = os.path.join(task_dir, "tests", "task_spec.json")
    oracle_path = os.path.join(task_dir, "tests", "oracle_answer.json")

    if not os.path.isfile(spec_path):
        return f"SKIP {task_id}: task_spec.json not found at {spec_path}"

    if not os.path.isfile(oracle_path):
        return f"SKIP {task_id}: oracle_answer.json not found at {oracle_path}"

    # Load both files
    spec = load_json(spec_path)
    oracle_answer = load_json(oracle_path)

    # Populate oracle fields
    oracle = spec.setdefault("artifacts", {}).setdefault("oracle", {})

    files = oracle_answer.get("files", [])
    symbols = oracle_answer.get("symbols", [])
    chain = oracle_answer.get("chain", [])

    oracle["required_files"] = [_normalize_file_entry(f) for f in files]
    oracle["required_symbols"] = symbols
    oracle["required_references"] = oracle.get("required_references", [])

    # Wrap chain as a single dependency chain entry
    if chain:
        oracle["dependency_chains"] = [{"steps": chain}]
    else:
        oracle["dependency_chains"] = []

    # Build evaluation checks
    checks = build_checks(oracle_check_types, oracle_answer)
    spec.setdefault("evaluation", {})["checks"] = checks

    changes = []
    if files:
        changes.append(f"{len(files)} files")
    if symbols:
        changes.append(f"{len(symbols)} symbols")
    if chain:
        changes.append(f"{len(chain)}-step chain")
    changes.append(f"{len(checks)} checks")

    if dry_run:
        return f"DRY-RUN {task_id}: would write {', '.join(changes)}"

    # Write updated spec
    with open(spec_path, "w") as f:
        json.dump(spec, f, indent=2)
        f.write("\n")

    return f"OK {task_id}: {', '.join(changes)}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hydrate task_spec.json oracle fields from oracle_answer.json"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be done without modifying files",
    )
    parser.add_argument(
        "--selection-file", default=DEFAULT_SELECTION,
        help="Path to selection JSON file (default: selected_mcp_tasks_121_141.json)",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.selection_file):
        print(f"ERROR: selection file not found: {args.selection_file}")
        return 1

    tasks = load_selection(args.selection_file)
    print(f"Hydrating {len(tasks)} tasks from {os.path.basename(args.selection_file)}")
    if args.dry_run:
        print("(dry-run mode)\n")
    else:
        print()

    ok_count = 0
    skip_count = 0
    for task in tasks:
        status = hydrate_task(task, args.dry_run)
        print(f"  {status}")
        if status.startswith("OK") or status.startswith("DRY-RUN"):
            ok_count += 1
        else:
            skip_count += 1

    print(f"\nDone: {ok_count} hydrated, {skip_count} skipped")
    return 0 if skip_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
