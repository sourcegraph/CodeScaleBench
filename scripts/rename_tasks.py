#!/usr/bin/env python3
"""Rename task folders and update all references per task_rename_map.json."""

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS = REPO_ROOT / "benchmarks"
RENAME_MAP = REPO_ROOT / "configs" / "task_rename_map.json"
SELECTED_TASKS = REPO_ROOT / "configs" / "selected_benchmark_tasks.json"


def update_toml_ids(toml_path: Path, old_name: str, new_name: str) -> int:
    """Update id/name/task_id fields in task.toml. Returns count of changes."""
    if not toml_path.exists():
        return 0
    text = toml_path.read_text()
    original = text

    # Replace various id fields that match the old name
    # [task] id = "old_name"
    text = re.sub(
        rf'(id\s*=\s*"){re.escape(old_name)}"',
        rf'\g<1>{new_name}"',
        text,
    )
    # [metadata] name = "old_name"
    text = re.sub(
        rf'(name\s*=\s*"){re.escape(old_name)}"',
        rf'\g<1>{new_name}"',
        text,
    )
    # [metadata] task_id = "old_name"
    text = re.sub(
        rf'(task_id\s*=\s*"){re.escape(old_name)}"',
        rf'\g<1>{new_name}"',
        text,
    )

    if text != original:
        toml_path.write_text(text)
        return 1
    return 0


def rename_folders(rename_map: dict, dry_run: bool = False) -> tuple[int, int]:
    """Rename task folders. Returns (success, fail) counts."""
    ok, fail = 0, 0
    for suite, mappings in rename_map.items():
        suite_dir = BENCHMARKS / suite
        if not suite_dir.is_dir():
            print(f"  SKIP: {suite} dir not found")
            continue
        for old_name, new_name in mappings.items():
            old_path = suite_dir / old_name
            new_path = suite_dir / new_name
            if old_name == new_name:
                ok += 1
                continue
            if not old_path.exists():
                print(f"  MISSING: {suite}/{old_name}")
                fail += 1
                continue
            if new_path.exists():
                print(f"  CONFLICT: {suite}/{new_name} already exists")
                fail += 1
                continue
            if dry_run:
                print(f"  DRY: {suite}/{old_name} -> {new_name}")
            else:
                old_path.rename(new_path)
                # Update task.toml inside
                toml_path = new_path / "task.toml"
                update_toml_ids(toml_path, old_name, new_name)
            ok += 1
    return ok, fail


def update_selected_tasks(rename_map: dict, dry_run: bool = False) -> int:
    """Update selected_benchmark_tasks.json. Returns count of changes."""
    with open(SELECTED_TASKS) as f:
        data = json.load(f)

    # Build flat old->new mapping
    flat_map = {}
    for suite, mappings in rename_map.items():
        for old_name, new_name in mappings.items():
            flat_map[old_name] = (new_name, suite)

    changes = 0
    for task in data["tasks"]:
        old_id = task["task_id"]
        if old_id in flat_map:
            new_name, suite = flat_map[old_id]
            if old_id != new_name:
                task["task_id"] = new_name
                task["task_dir"] = f"{suite}/{new_name}"
                changes += 1

    if not dry_run and changes > 0:
        with open(SELECTED_TASKS, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

    return changes


def main():
    dry_run = "--dry-run" in sys.argv

    with open(RENAME_MAP) as f:
        rename_map = json.load(f)

    total_tasks = sum(len(v) for v in rename_map.values())
    print(f"Rename map: {total_tasks} tasks across {len(rename_map)} suites")

    if dry_run:
        print("\n=== DRY RUN ===\n")

    # Step 1: Rename folders + update task.toml
    print("Step 1: Renaming folders...")
    ok, fail = rename_folders(rename_map, dry_run)
    print(f"  Folders: {ok} ok, {fail} failed")

    # Step 2: Update selected_benchmark_tasks.json
    print("Step 2: Updating selected_benchmark_tasks.json...")
    changes = update_selected_tasks(rename_map, dry_run)
    print(f"  Updated {changes} task entries")

    if fail > 0:
        print(f"\nWARNING: {fail} failures")
        return 1
    print(f"\nDone: {ok + changes} total changes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
