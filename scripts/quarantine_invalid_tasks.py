#!/usr/bin/env python3
"""Quarantine invalid task dirs from runs/official into archive/qa_needed.

Default rule:
  - MCP-enabled configs only (sourcegraph_full)
  - status == failed
  - mcp_total_calls == 0

When a task is selected by this rule, all config variants for the same
(suite, run_dir, task_name) are quarantined together to keep paired analysis
consistent.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from audit_traces import collect_all_tasks

MCP_CONFIGS = {"sourcegraph_full"}
REASON = "failed_zero_mcp_calls"


def _group_records(tasks: list[dict]) -> dict[tuple[str, str, str], list[dict]]:
    grouped: dict[tuple[str, str, str], list[dict]] = {}
    for t in tasks:
        key = (t["suite"], t["run_dir"], t["task_name"])
        grouped.setdefault(key, []).append(t)
    return grouped


def _select_invalid_keys(tasks: list[dict]) -> set[tuple[str, str, str]]:
    invalid: set[tuple[str, str, str]] = set()
    for t in tasks:
        if t["config"] not in MCP_CONFIGS:
            continue
        if t["status"] != "failed":
            continue
        if (t.get("mcp_total_calls") or 0) != 0:
            continue
        invalid.add((t["suite"], t["run_dir"], t["task_name"]))
    return invalid


def _build_moves(
    grouped: dict[tuple[str, str, str], list[dict]],
    invalid_keys: set[tuple[str, str, str]],
    runs_dir: Path,
    archive_root: Path,
) -> list[dict]:
    moves: list[dict] = []
    for key in sorted(invalid_keys):
        for rec in sorted(grouped.get(key, []), key=lambda r: (r["config"], r["task_dir"])):
            src = Path(rec["task_dir"])
            if not src.is_dir():
                continue
            try:
                relative = src.relative_to(runs_dir)
            except ValueError:
                continue
            dest = archive_root / REASON / relative
            moves.append({
                "suite": rec["suite"],
                "run_dir": rec["run_dir"],
                "config": rec["config"],
                "task_name": rec["task_name"],
                "status": rec["status"],
                "mcp_total_calls": rec.get("mcp_total_calls"),
                "source": str(src),
                "dest": str(dest),
            })
    return moves


def _execute_moves(moves: list[dict]) -> None:
    for mv in moves:
        src = Path(mv["source"])
        dest = Path(mv["dest"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            dest = dest.parent / f"{dest.name}__{ts}"
            mv["dest"] = str(dest)
        shutil.move(str(src), str(dest))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs-dir",
        default="runs/official",
        help="Path to runs/official directory (default: runs/official)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually move task dirs (default: dry-run).",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    args = parser.parse_args()

    runs_dir = Path(args.runs_dir).absolute()
    archive_root = runs_dir / "archive" / "qa_needed"
    tasks = collect_all_tasks()
    grouped = _group_records(tasks)
    invalid_keys = _select_invalid_keys(tasks)
    moves = _build_moves(grouped, invalid_keys, runs_dir, archive_root)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runs_dir": str(runs_dir),
        "reason": REASON,
        "invalid_task_keys": len(invalid_keys),
        "task_dirs_to_quarantine": len(moves),
        "dry_run": not args.execute,
        "moves": moves,
    }

    if args.execute and moves:
        _execute_moves(moves)
        report["dry_run"] = False
        report_path = archive_root / f"quarantine_report_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2))
        report["report_path"] = str(report_path)

    if args.format == "json":
        print(json.dumps(report, indent=2))
    else:
        print(f"Invalid task keys: {report['invalid_task_keys']}")
        print(f"Task dirs to quarantine: {report['task_dirs_to_quarantine']}")
        print(f"Dry run: {report['dry_run']}")
        for mv in moves:
            print(
                f"- {mv['suite']} {mv['config']} {mv['task_name']}\n"
                f"  {mv['source']} -> {mv['dest']}"
            )
        if report.get("report_path"):
            print(f"Report: {report['report_path']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
