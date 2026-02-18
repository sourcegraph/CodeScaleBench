#!/usr/bin/env python3
"""Scan SWE-bench Pro runs for errored tasks and produce a summary report.

Scans all swebenchpro_selected_opus_* and swebenchpro_gapfill_* run directories
under runs/official/ for task-level and batch-level errors.

Handles two types of errors:
1. Task-level: result.json inside task dirs (task_name__hash/) with non-null exception_info
2. Early failures: batch-level result.json with n_errors > 0 but no task subdirectory
   (task failed before creating a task dir, e.g., Docker image not found)

Output: prints a human-readable report and saves JSON to /tmp/ccb_swebench_errors.json
"""

import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs" / "official"
OUTPUT_JSON = Path("/tmp/ccb_swebench_errors.json")

# Run directory prefixes to scan
RUN_DIR_PREFIXES = ("swebenchpro_selected_opus_", "swebenchpro_gapfill_")

# ── Error fingerprinting (adapted from status_fingerprints.py) ─────────

ERROR_FINGERPRINTS = [
    (
        "token_refresh_403",
        re.compile(r"403|Forbidden|token.*refresh|refresh.*token|credentials.*expired", re.IGNORECASE),
        "OAuth token refresh failure (HTTP 403)",
    ),
    (
        "verifier_parse_error",
        re.compile(r"verifier.*(?:parse|json|decode|invalid)|JSONDecodeError.*verifier|reward.*parse", re.IGNORECASE),
        "Verifier output parse error",
    ),
    (
        "api_500",
        re.compile(r"500\s*Internal Server Error|api.*500|server.*error.*5\d{2}", re.IGNORECASE),
        "API 500 server error",
    ),
    (
        "api_rate_limit",
        re.compile(r"rate.?limit|429|too many requests|throttl|overloaded", re.IGNORECASE),
        "API rate limit / overloaded",
    ),
    (
        "timeout",
        re.compile(r"timeout|timed?\s*out|deadline exceeded|SIGTERM|killed.*signal", re.IGNORECASE),
        "Task timeout",
    ),
    (
        "mcp_connection",
        re.compile(r"mcp.*(?:connect|refused|unavailable|error)|sourcegraph.*(?:connect|error|fail)", re.IGNORECASE),
        "MCP server connection failure",
    ),
    (
        "docker_image_not_found",
        re.compile(r"not found|no such image|manifest unknown|pull.*fail", re.IGNORECASE),
        "Docker image not found",
    ),
    (
        "docker_compose_fail",
        re.compile(r"docker.*(?:compose|build|pull).*fail|container.*(?:exit|crash|fail)|OOMKill", re.IGNORECASE),
        "Docker/container failure",
    ),
    (
        "import_error",
        re.compile(r"ImportError|ModuleNotFoundError|No module named|cannot import", re.IGNORECASE),
        "Python import error",
    ),
    (
        "permission_denied",
        re.compile(r"permission denied|EACCES|Operation not permitted", re.IGNORECASE),
        "Permission denied",
    ),
    (
        "git_error",
        re.compile(r"fatal:.*git|git.*(?:clone|checkout|pull).*fail|repository not found", re.IGNORECASE),
        "Git operation failure",
    ),
]


def classify_error(text: str) -> tuple[str, str]:
    """Classify error text into a fingerprint category.

    Returns (fingerprint_id, label).
    """
    if not text or not text.strip():
        return ("unknown", "Unknown error")

    for fp_id, pattern, label in ERROR_FINGERPRINTS:
        if pattern.search(text):
            return (fp_id, label)

    return ("unknown", "Unknown error")


def extract_exception_text(exception_info) -> str:
    """Convert exception_info (dict, str, or other) to a searchable string."""
    if exception_info is None:
        return ""
    if isinstance(exception_info, dict):
        parts = [
            str(exception_info.get("exception_type", exception_info.get("type", ""))),
            str(exception_info.get("exception_message", exception_info.get("message", ""))),
            str(exception_info.get("exception_traceback", exception_info.get("traceback", ""))),
        ]
        return " ".join(parts)
    return str(exception_info)


def extract_config_from_path(fpath: str) -> str:
    """Extract config name (baseline, sourcegraph_full) from path."""
    parts = fpath.split("/")
    for config in ("baseline", "sourcegraph_full"):
        if config in parts:
            return config
    return "unknown"


def extract_run_dir_from_path(fpath: str) -> str:
    """Extract the top-level run directory name from path."""
    parts = fpath.split("/")
    for part in parts:
        for prefix in RUN_DIR_PREFIXES:
            if part.startswith(prefix):
                return part
    return "unknown"


def extract_task_short_name(task_name: str) -> str:
    """Extract a readable short name from the full task_name field."""
    # task_name typically looks like:
    #   instance_gravitational__teleport-8302d467...-vce94f93...
    # We want: instance_gravitational__teleport
    # Or from trial_name: instance_gravitational__teleport__TAUQJFn
    # Strip the hash suffix
    if "__" in task_name:
        parts = task_name.split("__")
        if len(parts) >= 2:
            # Return first two parts (org__repo)
            return "__".join(parts[:2])
    return task_name


def scan_runs():
    """Scan all SWE-bench Pro run directories for errors.

    Returns a list of error records.
    """
    errors = []

    for run_dir_name in sorted(os.listdir(RUNS_DIR)):
        matches_prefix = any(run_dir_name.startswith(p) for p in RUN_DIR_PREFIXES)
        if not matches_prefix:
            continue

        run_dir = RUNS_DIR / run_dir_name
        if not run_dir.is_dir():
            continue

        for root, dirs, files in os.walk(run_dir):
            if "result.json" not in files:
                continue

            fpath = os.path.join(root, "result.json")
            try:
                data = json.loads(Path(fpath).read_text())
            except (json.JSONDecodeError, OSError):
                continue

            # ── Case 1: Task-level result with exception_info ──
            if "task_name" in data:
                exception_info = data.get("exception_info")
                if exception_info is not None:
                    exc_text = extract_exception_text(exception_info)
                    fp_id, fp_label = classify_error(exc_text)
                    config = extract_config_from_path(fpath)
                    run_dir_id = extract_run_dir_from_path(fpath)

                    task_name = data.get("task_name", "")
                    trial_name = data.get("trial_name", "")

                    errors.append({
                        "source": "task_result",
                        "run_dir": run_dir_id,
                        "config": config,
                        "task_name": task_name,
                        "trial_name": trial_name,
                        "task_short": extract_task_short_name(trial_name or task_name),
                        "error_type": fp_id,
                        "error_label": fp_label,
                        "exception_type": (
                            exception_info.get("exception_type", exception_info.get("type", ""))
                            if isinstance(exception_info, dict) else ""
                        ),
                        "exception_message_snippet": exc_text[:300],
                        "result_json_path": fpath,
                    })

            # ── Case 2: Batch-level result with errors but no task dir ──
            elif "n_total_trials" in data and "stats" in data:
                n_errors = data.get("stats", {}).get("n_errors", 0)
                if n_errors > 0:
                    # Check if there is a task subdirectory
                    parent = Path(root)
                    task_dirs = [
                        x for x in parent.iterdir()
                        if x.is_dir() and "__" in x.name
                    ]
                    if task_dirs:
                        # Task dir exists -- the task-level result.json should
                        # have been caught in Case 1. Skip to avoid double-counting.
                        continue

                    # No task dir: early failure (e.g., Docker build failed)
                    config = extract_config_from_path(fpath)
                    run_dir_id = extract_run_dir_from_path(fpath)

                    # Extract task names from exception_stats
                    exc_stats = {}
                    for eval_data in data.get("stats", {}).get("evals", {}).values():
                        exc_stats.update(eval_data.get("exception_stats", {}))

                    # Read job.log for error details
                    job_log_path = parent / "job.log"
                    log_text = ""
                    if job_log_path.exists():
                        try:
                            log_text = job_log_path.read_text()
                        except OSError:
                            pass

                    fp_id, fp_label = classify_error(log_text)

                    for exc_type, trial_names in exc_stats.items():
                        for tn in trial_names:
                            errors.append({
                                "source": "batch_early_failure",
                                "run_dir": run_dir_id,
                                "config": config,
                                "task_name": "",
                                "trial_name": tn,
                                "task_short": extract_task_short_name(tn),
                                "error_type": fp_id,
                                "error_label": fp_label,
                                "exception_type": exc_type,
                                "exception_message_snippet": log_text[:300],
                                "result_json_path": fpath,
                            })

    return errors


def build_report(errors: list[dict]) -> dict:
    """Build a structured summary report from error records."""
    # Totals
    total = len(errors)

    # By error type
    by_type = defaultdict(int)
    for e in errors:
        by_type[e["error_type"]] += 1

    # By config
    by_config = defaultdict(int)
    for e in errors:
        by_config[e["config"]] += 1

    # By run dir
    by_run = defaultdict(int)
    for e in errors:
        by_run[e["run_dir"]] += 1

    # Task listing
    task_list = []
    for e in errors:
        task_list.append({
            "run_dir": e["run_dir"],
            "config": e["config"],
            "trial_name": e["trial_name"],
            "task_short": e["task_short"],
            "error_type": e["error_type"],
            "error_label": e["error_label"],
            "exception_type": e["exception_type"],
            "source": e["source"],
            "result_json_path": e["result_json_path"],
        })

    return {
        "total_errored_runs": total,
        "error_breakdown_by_type": dict(sorted(by_type.items(), key=lambda x: -x[1])),
        "error_breakdown_by_config": dict(sorted(by_config.items(), key=lambda x: -x[1])),
        "error_breakdown_by_run_dir": dict(sorted(by_run.items(), key=lambda x: -x[1])),
        "errored_tasks": task_list,
    }


def print_report(report: dict):
    """Print a human-readable summary."""
    print("=" * 80)
    print("SWE-BENCH PRO ERROR REPORT")
    print("=" * 80)
    print()

    print(f"Total errored runs: {report['total_errored_runs']}")
    print()

    print("── Error Breakdown by Type ──")
    for etype, count in report["error_breakdown_by_type"].items():
        print(f"  {etype:30s}  {count:3d}")
    print()

    print("── Error Breakdown by Config ──")
    for config, count in report["error_breakdown_by_config"].items():
        print(f"  {config:30s}  {count:3d}")
    print()

    print("── Error Breakdown by Run Directory ──")
    for run_dir, count in report["error_breakdown_by_run_dir"].items():
        print(f"  {run_dir}")
        print(f"    count: {count}")
    print()

    print("── Errored Tasks ──")
    print(f"{'#':>3s}  {'Config':20s}  {'Error Type':25s}  {'Trial Name'}")
    print("-" * 100)
    for i, task in enumerate(report["errored_tasks"], 1):
        print(f"{i:3d}  {task['config']:20s}  {task['error_type']:25s}  {task['trial_name']}")
    print()

    # Additional detail: exception snippets
    print("── Error Details ──")
    for i, task in enumerate(report["errored_tasks"], 1):
        print(f"\n[{i}] {task['trial_name']}")
        print(f"    Config:    {task['config']}")
        print(f"    Run dir:   {task['run_dir']}")
        print(f"    Type:      {task['error_type']} ({task['error_label']})")
        print(f"    Exception: {task['exception_type']}")
        print(f"    Source:    {task['source']}")
        print(f"    Path:      {task['result_json_path']}")


def main():
    if not RUNS_DIR.is_dir():
        print(f"ERROR: Runs directory not found: {RUNS_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"Scanning: {RUNS_DIR}")
    print(f"Prefixes: {RUN_DIR_PREFIXES}")
    print()

    errors = scan_runs()
    report = build_report(errors)

    print_report(report)

    # Save JSON
    OUTPUT_JSON.write_text(json.dumps(report, indent=2))
    print(f"\nJSON report saved to: {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
