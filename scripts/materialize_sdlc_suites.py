#!/usr/bin/env python3
"""Materialize SDLC suite directories from migration_map.json.

Default mode is symlink to avoid duplicating task contents.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def load_map(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "mappings" not in data:
        raise ValueError(f"Invalid migration map format: {path}")
    return data


def task_id_variants(old_suite: str, task_id: str) -> List[str]:
    variants = [task_id]
    if old_suite == "ccb_dibench" and task_id.startswith("ccb_dibench-"):
        variants.append(task_id[len("ccb_dibench-") :])
        variants.append("dibench-" + task_id[len("ccb_dibench-") :])
    if old_suite == "ccb_sweperf" and task_id.startswith("ccb_sweperf-"):
        variants.append(task_id[len("ccb_sweperf-") :])
        variants.append("sweperf-" + task_id[len("ccb_sweperf-") :])
    if "__" in task_id:
        variants.append(task_id.replace("__", "-"))
    # Preserve order, remove duplicates
    seen = set()
    deduped: List[str] = []
    for v in variants:
        if v not in seen:
            deduped.append(v)
            seen.add(v)
    return deduped


def resolve_source(benchmarks_dir: Path, old_suite: str, task_id: str) -> Optional[Path]:
    for variant in task_id_variants(old_suite, task_id):
        candidates = [
            benchmarks_dir / old_suite / variant,
            benchmarks_dir / old_suite / "tasks" / variant,
            benchmarks_dir / "archive" / old_suite / variant,
            benchmarks_dir / "archive" / old_suite / "tasks" / variant,
        ]
        for c in candidates:
            if c.is_dir():
                return c

    # Fallback: search for directory named any variant containing task.toml
    for variant in task_id_variants(old_suite, task_id):
        for p in benchmarks_dir.rglob(variant):
            if p.is_dir() and (p / "task.toml").is_file():
                return p
    return None


def ensure_empty_or_create(suite_dir: Path, clean: bool, dry_run: bool) -> None:
    if suite_dir.exists() and clean:
        if dry_run:
            return
        shutil.rmtree(suite_dir)
    if not suite_dir.exists() and not dry_run:
        suite_dir.mkdir(parents=True, exist_ok=True)


def make_link_or_copy(src: Path, dst: Path, mode: str, dry_run: bool) -> str:
    if dst.exists() or dst.is_symlink():
        if dst.is_symlink() and mode == "symlink":
            current = os.readlink(dst)
            expected = os.path.relpath(src, dst.parent)
            if current == expected:
                return "unchanged"
        raise FileExistsError(f"Destination already exists: {dst}")

    if dry_run:
        return "planned"

    if mode == "symlink":
        rel = os.path.relpath(src, dst.parent)
        dst.symlink_to(rel, target_is_directory=True)
    elif mode == "copy":
        shutil.copytree(src, dst, symlinks=True)
    elif mode == "move":
        shutil.move(str(src), str(dst))
    else:
        raise ValueError(f"Unknown mode: {mode}")
    return "created"


def main() -> int:
    parser = argparse.ArgumentParser(description="Materialize SDLC suite directories from migration map")
    parser.add_argument("--map", dest="map_path", default="migration_map.json", help="Path to migration_map.json")
    parser.add_argument("--benchmarks-dir", default="benchmarks", help="Benchmarks root directory")
    parser.add_argument(
        "--mode",
        choices=["symlink", "copy", "move"],
        default="symlink",
        help="How to materialize mapped tasks",
    )
    parser.add_argument("--clean", action="store_true", help="Delete target suite dirs before materialization")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without writing files")
    parser.add_argument(
        "--report",
        default="docs/sdlc_materialization_report.json",
        help="Write JSON report to this path",
    )
    args = parser.parse_args()

    map_path = Path(args.map_path)
    benchmarks_dir = Path(args.benchmarks_dir)
    report_path = Path(args.report)

    data = load_map(map_path)
    metadata = data.get("metadata", {})
    mappings: Dict[str, dict] = data.get("mappings", {})
    target_suites: List[str] = metadata.get("target_suites", [])

    if not target_suites:
        raise ValueError("No metadata.target_suites found in migration map")

    suite_dir_map = {suite: benchmarks_dir / suite for suite in target_suites}
    for sd in suite_dir_map.values():
        ensure_empty_or_create(sd, clean=args.clean, dry_run=args.dry_run)

    status_counts = Counter()
    suite_counts = Counter()
    missing_sources: List[dict] = []
    created: List[dict] = []

    mapped_items: List[Tuple[str, dict]] = [
        (task_id, spec)
        for task_id, spec in mappings.items()
        if spec.get("status") == "mapped" and spec.get("new_suite") in suite_dir_map
    ]

    # Deterministic ordering
    mapped_items.sort(key=lambda x: (x[1].get("new_suite", ""), x[0]))

    for task_id, spec in mapped_items:
        old_suite = spec.get("old_suite")
        new_suite = spec.get("new_suite")
        status_counts[spec.get("status", "unknown")] += 1

        src = resolve_source(benchmarks_dir, old_suite, task_id)
        if src is None:
            missing_sources.append({"task_id": task_id, "old_suite": old_suite, "new_suite": new_suite})
            continue

        dst = suite_dir_map[new_suite] / task_id
        try:
            result = make_link_or_copy(src, dst, mode=args.mode, dry_run=args.dry_run)
        except Exception as e:  # noqa: BLE001
            missing_sources.append(
                {
                    "task_id": task_id,
                    "old_suite": old_suite,
                    "new_suite": new_suite,
                    "error": str(e),
                }
            )
            continue

        suite_counts[new_suite] += 1
        created.append(
            {
                "task_id": task_id,
                "old_suite": old_suite,
                "new_suite": new_suite,
                "source": str(src),
                "target": str(dst),
                "result": result,
            }
        )

    # Include full status counts from map for context
    full_status_counts = Counter(spec.get("status", "unknown") for spec in mappings.values())

    report = {
        "migration_map": str(map_path),
        "benchmarks_dir": str(benchmarks_dir),
        "mode": args.mode,
        "dry_run": args.dry_run,
        "clean": args.clean,
        "target_suites": target_suites,
        "counts": {
            "total_mappings": len(mappings),
            "status_counts": dict(full_status_counts),
            "mapped_targeted": len(mapped_items),
            "materialized": len(created),
            "missing_or_failed": len(missing_sources),
            "by_suite": dict(suite_counts),
        },
        "missing_or_failed": missing_sources,
    }

    if not args.dry_run:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    print("SDLC materialization summary")
    print(f"  mode: {args.mode}")
    print(f"  dry_run: {args.dry_run}")
    print(f"  targeted mapped tasks: {len(mapped_items)}")
    print(f"  materialized: {len(created)}")
    print(f"  missing_or_failed: {len(missing_sources)}")
    print("  by_suite:")
    for suite in target_suites:
        print(f"    {suite}: {suite_counts.get(suite, 0)}")

    if missing_sources:
        print("\nMissing/failed examples:")
        for item in missing_sources[:10]:
            print(f"  - {item}")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
