#!/usr/bin/env python3
"""Validate that runs/official is a curated, analysis-safe dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from official_integrity import evaluate_official_integrity


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs-dir",
        default="./runs/official",
        help="Path to runs/official directory (default: ./runs/official)",
    )
    parser.add_argument(
        "--allow-missing-triage",
        action="store_true",
        help="Do not fail when triage.json is missing/invalid/pending.",
    )
    parser.add_argument(
        "--allow-unknown-prefix",
        action="store_true",
        help="Do not fail on run directories with unknown prefixes.",
    )
    parser.add_argument(
        "--skip-freshness-check",
        action="store_true",
        help="Skip manifest freshness check against tracked run mtimes.",
    )
    parser.add_argument(
        "--check-mcp-trace-health",
        action="store_true",
        help="Fail if MCP-enabled failed tasks have zero MCP calls.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "text"),
        default="text",
        help="Output format (default: text)",
    )
    args = parser.parse_args()

    result = evaluate_official_integrity(
        Path(args.runs_dir),
        require_triage=not args.allow_missing_triage,
        fail_on_unknown_prefix=not args.allow_unknown_prefix,
        check_manifest_freshness=not args.skip_freshness_check,
        check_mcp_trace_health=args.check_mcp_trace_health,
    )

    if args.format == "json":
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "errors": result.errors,
                    "warnings": result.warnings,
                    "details": result.details,
                },
                indent=2,
            )
        )
    else:
        print(f"Integrity OK: {result.ok}")
        if result.errors:
            print("Errors:")
            for err in result.errors:
                print(f"  - {err}")
        if result.warnings:
            print("Warnings:")
            for warn in result.warnings:
                print(f"  - {warn}")
        print("Summary:")
        for key, val in result.details.items():
            if key in {"unknown_prefix_dirs", "triage_issues", "tracked_not_on_disk",
                       "triage_include_not_in_manifest", "unmanaged_run_dirs", "mcp_failed_zero_calls",
                       "mcp_init_missing_with_transcript", "mcp_init_missing_no_transcript"}:
                continue
            print(f"  {key}: {val}")
        if result.details.get("unmanaged_run_dirs"):
            print("Unmanaged run dirs:")
            for name in result.details["unmanaged_run_dirs"]:
                print(f"  - {name}")
        if result.details.get("mcp_failed_zero_calls"):
            print("MCP failed-zero-call tasks:")
            for item in result.details["mcp_failed_zero_calls"]:
                print(
                    f"  - {item['suite']} {item['config']} {item['task_name']} "
                    f"({item['run_dir']})"
                )
        if result.details.get("mcp_init_missing_with_transcript"):
            print("MCP init missing (transcript present):")
            for item in result.details["mcp_init_missing_with_transcript"]:
                print(
                    f"  - {item['suite']} {item['config']} {item['task_name']} "
                    f"({item['run_dir']})"
                )
        if result.details.get("mcp_init_missing_no_transcript"):
            print("MCP init missing (no transcript; likely setup/auth failure):")
            for item in result.details["mcp_init_missing_no_transcript"]:
                print(
                    f"  - {item['suite']} {item['config']} {item['task_name']} "
                    f"({item['run_dir']})"
                )

    return 0 if result.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
