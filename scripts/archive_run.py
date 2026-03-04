#!/usr/bin/env python3
"""Archive old completed run directories to save disk and speed up scans.

Moves run directories older than N days to runs/official/archive/,
optionally compressing large files.

Usage:
    # Show what would be archived (dry-run, default)
    python3 scripts/archive_run.py --older-than 7

    # Actually archive
    python3 scripts/archive_run.py --older-than 7 --execute

    # Archive a specific run directory
    python3 scripts/archive_run.py --run-dir pytorch_opus_20260203_160607

    # List archived runs
    python3 scripts/archive_run.py --list-archived
"""

import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs" / "official"
ARCHIVE_DIR = RUNS_DIR / "archive"

# These are already skipped by aggregate_status.py
SKIP_PATTERNS = ["__broken_verifier", "validation_test", "archive"]


def should_skip(dirname: str) -> bool:
    return any(pat in dirname for pat in SKIP_PATTERNS)


def get_dir_age_days(dirpath: Path) -> float:
    """Days since directory was last modified."""
    try:
        mtime = dirpath.stat().st_mtime
        return (time.time() - mtime) / 86400.0
    except OSError:
        return 0.0


def get_dir_size_mb(dirpath: Path) -> float:
    """Total size of directory in MB."""
    total = 0
    try:
        for f in dirpath.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    except OSError:
        pass
    return total / (1024 * 1024)


def count_results(dirpath: Path) -> int:
    """Count result.json files in a run directory."""
    return sum(1 for _ in dirpath.rglob("result.json"))


def find_archivable_runs(older_than_days: float) -> list[dict]:
    """Find run directories eligible for archival."""
    candidates = []

    if not RUNS_DIR.exists():
        return candidates

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        if should_skip(run_dir.name):
            continue

        age_days = get_dir_age_days(run_dir)
        if age_days < older_than_days:
            continue

        size_mb = get_dir_size_mb(run_dir)
        result_count = count_results(run_dir)

        candidates.append({
            "name": run_dir.name,
            "path": str(run_dir),
            "age_days": round(age_days, 1),
            "size_mb": round(size_mb, 1),
            "result_count": result_count,
        })

    return candidates


def archive_run(run_dir: Path, compress: bool = False) -> dict:
    """Move a run directory to the archive."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    dest = ARCHIVE_DIR / run_dir.name
    if dest.exists():
        # Append timestamp to avoid collision
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = ARCHIVE_DIR / f"{run_dir.name}__{ts}"

    size_before = get_dir_size_mb(run_dir)

    if compress:
        # Create a compressed tar archive
        archive_path = ARCHIVE_DIR / f"{run_dir.name}.tar.gz"
        shutil.make_archive(
            str(ARCHIVE_DIR / run_dir.name),
            "gztar",
            root_dir=str(run_dir.parent),
            base_dir=run_dir.name,
        )
        # Remove original
        shutil.rmtree(run_dir)
        size_after = archive_path.stat().st_size / (1024 * 1024)
        return {
            "action": "compressed",
            "source": str(run_dir),
            "dest": str(archive_path),
            "size_before_mb": round(size_before, 1),
            "size_after_mb": round(size_after, 1),
            "savings_mb": round(size_before - size_after, 1),
        }
    else:
        # Just move
        shutil.move(str(run_dir), str(dest))
        return {
            "action": "moved",
            "source": str(run_dir),
            "dest": str(dest),
            "size_mb": round(size_before, 1),
        }


def list_archived() -> list[dict]:
    """List directories in the archive."""
    if not ARCHIVE_DIR.exists():
        return []

    archived = []
    for entry in sorted(ARCHIVE_DIR.iterdir()):
        if entry.is_dir():
            archived.append({
                "name": entry.name,
                "size_mb": round(get_dir_size_mb(entry), 1),
                "result_count": count_results(entry),
            })
        elif entry.suffix in (".gz", ".tar"):
            archived.append({
                "name": entry.name,
                "size_mb": round(entry.stat().st_size / (1024 * 1024), 1),
                "result_count": "n/a (compressed)",
            })

    return archived


def main():
    parser = argparse.ArgumentParser(
        description="Archive old benchmark run directories."
    )
    parser.add_argument("--older-than", type=float, default=None, metavar="DAYS",
                        help="Archive runs older than N days")
    parser.add_argument("--run-dir", default=None,
                        help="Archive a specific run directory by name")
    parser.add_argument("--compress", action="store_true",
                        help="Compress archived runs as .tar.gz (saves disk but slower)")
    parser.add_argument("--execute", action="store_true",
                        help="Actually perform the archive (default: dry-run)")
    parser.add_argument("--list-archived", action="store_true",
                        help="List already-archived runs")
    parser.add_argument("--format", choices=["table", "json"], default="table")
    args = parser.parse_args()

    if args.list_archived:
        archived = list_archived()
        if args.format == "json":
            print(json.dumps(archived, indent=2))
        else:
            if not archived:
                print("No archived runs found.")
            else:
                print(f"Archived runs ({len(archived)}):")
                for a in archived:
                    print(f"  {a['name']:50s}  {a['size_mb']:>8.1f} MB  {a['result_count']} results")
        return

    if args.run_dir:
        run_path = RUNS_DIR / args.run_dir
        if not run_path.is_dir():
            print(f"ERROR: Run directory not found: {run_path}", file=sys.stderr)
            sys.exit(1)

        if args.execute:
            result = archive_run(run_path, compress=args.compress)
            print(f"Archived: {result['source']} -> {result['dest']}")
            if "savings_mb" in result:
                print(f"  Compressed: {result['size_before_mb']}MB -> {result['size_after_mb']}MB "
                      f"(saved {result['savings_mb']}MB)")
        else:
            size = get_dir_size_mb(run_path)
            results = count_results(run_path)
            print(f"Would archive: {args.run_dir} ({size:.1f}MB, {results} results)")
            print("Use --execute to perform the archive.")
        return

    if args.older_than is None:
        parser.print_help()
        sys.exit(1)

    candidates = find_archivable_runs(args.older_than)

    if not candidates:
        print(f"No run directories older than {args.older_than} days found.")
        return

    total_size = sum(c["size_mb"] for c in candidates)

    if args.format == "json":
        print(json.dumps({
            "candidates": candidates,
            "total_size_mb": round(total_size, 1),
            "count": len(candidates),
            "dry_run": not args.execute,
        }, indent=2))
        return

    if args.execute:
        print(f"Archiving {len(candidates)} run directories ({total_size:.1f}MB total)...")
        for c in candidates:
            run_path = Path(c["path"])
            result = archive_run(run_path, compress=args.compress)
            print(f"  Archived: {c['name']} ({c['size_mb']}MB, {c['result_count']} results)")

        print(f"\nDone. {len(candidates)} directories moved to {ARCHIVE_DIR}")
    else:
        print(f"Would archive {len(candidates)} run directories ({total_size:.1f}MB total):")
        for c in candidates:
            print(f"  {c['name']:50s}  {c['age_days']:>6.1f} days  "
                  f"{c['size_mb']:>8.1f} MB  {c['result_count']} results")
        print(f"\nUse --execute to perform the archive.")


if __name__ == "__main__":
    main()
