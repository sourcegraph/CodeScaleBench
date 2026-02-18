#!/usr/bin/env python3
"""Integrity checks for curated runs/official datasets."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from official_runs import (
    detect_suite,
    load_manifest,
    load_prefix_map,
    read_triage,
    top_level_run_dirs,
    tracked_run_dirs_from_manifest,
)


@dataclass
class IntegrityResult:
    ok: bool
    errors: list[str]
    warnings: list[str]
    details: dict


def _parse_iso_ts(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def evaluate_official_integrity(
    runs_dir: Path,
    *,
    require_triage: bool = True,
    fail_on_unknown_prefix: bool = True,
    check_manifest_freshness: bool = True,
    check_mcp_trace_health: bool = False,
) -> IntegrityResult:
    errors: list[str] = []
    warnings: list[str] = []

    project_root = Path(__file__).resolve().parent.parent
    manifest_path = runs_dir / "MANIFEST.json"

    if not runs_dir.is_dir():
        return IntegrityResult(False, [f"runs_dir_not_found:{runs_dir}"], [], {})
    if not manifest_path.is_file():
        return IntegrityResult(False, [f"manifest_missing:{manifest_path}"], [], {})

    manifest = load_manifest(manifest_path)
    prefix_map = load_prefix_map(project_root)
    top_dirs = top_level_run_dirs(runs_dir)
    tracked = tracked_run_dirs_from_manifest(manifest)

    include_dirs: set[str] = set()
    exclude_dirs: set[str] = set()
    pending_dirs: set[str] = set()
    triage_issues: dict[str, str] = {}
    unknown_prefix_dirs: set[str] = set()

    for run_dir in top_dirs:
        suite = detect_suite(run_dir.name, prefix_map)
        if suite is None:
            unknown_prefix_dirs.add(run_dir.name)
        triage, triage_err = read_triage(run_dir)
        if triage is None:
            if triage_err:
                triage_issues[run_dir.name] = triage_err
            if require_triage:
                pending_dirs.add(run_dir.name)
            continue
        decision = triage.get("decision")
        if triage_err:
            triage_issues[run_dir.name] = triage_err
            pending_dirs.add(run_dir.name)
        elif decision == "include":
            include_dirs.add(run_dir.name)
        elif decision == "exclude":
            exclude_dirs.add(run_dir.name)
        else:
            pending_dirs.add(run_dir.name)

    if fail_on_unknown_prefix and unknown_prefix_dirs:
        errors.append(f"unknown_prefix_dirs:{len(unknown_prefix_dirs)}")
    elif unknown_prefix_dirs:
        warnings.append(f"unknown_prefix_dirs:{len(unknown_prefix_dirs)}")

    if require_triage:
        missing_or_invalid = sorted(
            [name for name in triage_issues.keys() if name not in exclude_dirs and name not in include_dirs]
        )
        if missing_or_invalid:
            errors.append(f"triage_missing_or_invalid:{len(missing_or_invalid)}")
        if pending_dirs:
            errors.append(f"triage_pending:{len(pending_dirs)}")

    tracked_not_on_disk = sorted([name for name in tracked if not (runs_dir / name).is_dir()])
    if tracked_not_on_disk:
        errors.append(f"tracked_missing_on_disk:{len(tracked_not_on_disk)}")

    # Any tracked run that triage marked exclude is a hard mismatch.
    tracked_but_excluded = sorted([name for name in tracked if name in exclude_dirs])
    if tracked_but_excluded:
        errors.append(f"tracked_but_triage_exclude:{len(tracked_but_excluded)}")

    # Any triage include that is not tracked likely means stale manifest.
    include_not_tracked = sorted([name for name in include_dirs if name not in tracked])
    if include_not_tracked:
        errors.append(f"triage_include_not_in_manifest:{len(include_not_tracked)}")

    # Any on-disk run that is neither tracked nor triage-excluded is drift.
    top_names = {p.name for p in top_dirs}
    unmanaged = sorted([name for name in top_names if name not in tracked and name not in exclude_dirs])
    if unmanaged:
        errors.append(f"unmanaged_run_dirs:{len(unmanaged)}")

    if check_manifest_freshness:
        generated = _parse_iso_ts(manifest.get("generated", ""))
        if generated is None:
            errors.append("manifest_generated_timestamp_invalid")
        else:
            latest_mtime: datetime | None = None
            for name in tracked:
                p = runs_dir / name
                if not p.is_dir():
                    continue
                mt = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
                if latest_mtime is None or mt > latest_mtime:
                    latest_mtime = mt
            if latest_mtime and generated < latest_mtime:
                errors.append("manifest_stale_vs_tracked_mtime")

    # Optional: fail if MCP-enabled runs have failed tasks with zero MCP calls.
    # This catches runs that are not valid for MCP impact analysis and should be
    # quarantined/QA'd before being treated as official analysis input.
    mcp_failed_zero_calls: list[dict] = []
    mcp_init_missing_with_transcript: list[dict] = []
    mcp_init_missing_no_transcript: list[dict] = []
    if check_mcp_trace_health:
        from audit_traces import collect_all_tasks  # local import to avoid startup overhead

        for task in collect_all_tasks():
            if task.get("config") not in {"sourcegraph_full"}:
                continue

            if not task.get("has_mcp_tools_available", False):
                rec = {
                    "suite": task.get("suite"),
                    "run_dir": task.get("run_dir"),
                    "config": task.get("config"),
                    "task_name": task.get("task_name"),
                    "task_dir": task.get("task_dir"),
                    "status": task.get("status"),
                }
                if task.get("has_transcript"):
                    mcp_init_missing_with_transcript.append(rec)
                else:
                    mcp_init_missing_no_transcript.append(rec)

            if task.get("status") != "failed":
                continue
            if (task.get("mcp_total_calls") or 0) != 0:
                continue
            mcp_failed_zero_calls.append({
                "suite": task.get("suite"),
                "run_dir": task.get("run_dir"),
                "config": task.get("config"),
                "task_name": task.get("task_name"),
                "task_dir": task.get("task_dir"),
            })
        if mcp_failed_zero_calls:
            errors.append(f"mcp_failed_zero_calls:{len(mcp_failed_zero_calls)}")
        if mcp_init_missing_with_transcript:
            errors.append(
                "mcp_init_missing_with_transcript:"
                f"{len(mcp_init_missing_with_transcript)}"
            )
        if mcp_init_missing_no_transcript:
            warnings.append(
                "mcp_init_missing_no_transcript:"
                f"{len(mcp_init_missing_no_transcript)}"
            )

    details = {
        "runs_dir": str(runs_dir),
        "manifest_path": str(manifest_path),
        "top_level_run_dirs": len(top_dirs),
        "tracked_run_dirs": len(tracked),
        "triage_include": len(include_dirs),
        "triage_exclude": len(exclude_dirs),
        "triage_pending": len(pending_dirs),
        "unknown_prefix_dirs": sorted(unknown_prefix_dirs),
        "triage_issues": triage_issues,
        "tracked_not_on_disk": tracked_not_on_disk,
        "triage_include_not_in_manifest": include_not_tracked,
        "unmanaged_run_dirs": unmanaged,
        "mcp_failed_zero_calls": mcp_failed_zero_calls,
        "mcp_init_missing_with_transcript": mcp_init_missing_with_transcript,
        "mcp_init_missing_no_transcript": mcp_init_missing_no_transcript,
    }
    return IntegrityResult(ok=not errors, errors=errors, warnings=warnings, details=details)
