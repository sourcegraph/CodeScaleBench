#!/usr/bin/env python3
"""Aggregate benchmark run status scanner.

Scans runs/official/ for task directories, classifies each task's status,
fingerprints errors, and produces structured summaries.

Usage:
    # JSON output (default)
    python3 scripts/aggregate_status.py

    # Compact table
    python3 scripts/aggregate_status.py --format table

    # Only failures
    python3 scripts/aggregate_status.py --failures-only --format table

    # Filter by suite or config
    python3 scripts/aggregate_status.py --suite ccb_pytorch --config baseline

    # Continuous watch mode
    python3 scripts/aggregate_status.py --format table --watch --interval 30

    # Write per-task status.json files
    python3 scripts/aggregate_status.py --write-status
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Ensure scripts/ is on path for sibling imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from status_fingerprints import fingerprint_error

# ---------------------------------------------------------------------------
# Constants (duplicated from generate_manifest.py for independence)
# ---------------------------------------------------------------------------

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs" / "official"

SKIP_PATTERNS = ["__broken_verifier", "validation_test", "archive"]

DIR_PREFIX_TO_SUITE = {
    "bigcode_mcp_": "ccb_largerepo",
    "codereview_": "ccb_codereview",
    "crossrepo_": "ccb_crossrepo",
    "dibench_": "ccb_dibench",
    "k8s_docs_": "ccb_k8sdocs",
    "locobench_": "ccb_locobench",
    "pytorch_": "ccb_pytorch",
    "repoqa_": "ccb_repoqa",
    "swebenchpro_": "ccb_swebenchpro",
    "sweperf_": "ccb_sweperf",
    "tac_": "ccb_tac",
}

CONFIGS = ["baseline", "sourcegraph_base", "sourcegraph_full"]


def should_skip(dirname: str) -> bool:
    return any(pat in dirname for pat in SKIP_PATTERNS)


def detect_suite(dirname: str) -> str | None:
    for prefix, suite in DIR_PREFIX_TO_SUITE.items():
        if dirname.startswith(prefix):
            return suite
    return None


# ---------------------------------------------------------------------------
# Task scanning
# ---------------------------------------------------------------------------

def _dir_mtime_age_hours(dirpath: Path) -> float:
    """Hours since directory was last modified."""
    try:
        mtime = dirpath.stat().st_mtime
        return (time.time() - mtime) / 3600.0
    except OSError:
        return 0.0


def _dir_mtime_iso(dirpath: Path) -> str:
    """Return mtime as ISO string."""
    try:
        mtime = dirpath.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except OSError:
        return ""


def _extract_task_name(dirname: str) -> str:
    """Strip __hash suffix from directory name to get task name."""
    parts = dirname.rsplit("__", 1)
    return parts[0] if len(parts) == 2 else dirname


def _read_log_tail(task_dir: Path, n: int = 10) -> list[str]:
    """Read last n lines from claude-code.txt transcript."""
    transcript = task_dir / "agent" / "claude-code.txt"
    if not transcript.is_file():
        return []
    try:
        text = transcript.read_text(errors="replace")
        lines = text.strip().splitlines()
        return lines[-n:]
    except OSError:
        return []


def _extract_reward(data: dict) -> float | None:
    """Extract reward from result.json data."""
    verifier = data.get("verifier_result") or {}
    rewards = verifier.get("rewards") or {}
    reward = rewards.get("reward")
    if reward is None:
        reward = rewards.get("score")
    if reward is not None:
        return float(reward)
    return None


def _extract_tokens(data: dict) -> dict:
    """Extract token counts from result.json."""
    agent_result = data.get("agent_result") or {}
    return {
        "input_tokens": agent_result.get("n_input_tokens"),
        "output_tokens": agent_result.get("n_output_tokens"),
    }


def classify_task(task_dir: Path, timeout_hours: float) -> dict:
    """Classify a single task directory into a status record."""
    result_file = task_dir / "result.json"
    task_name = _extract_task_name(task_dir.name)
    dir_mtime = _dir_mtime_iso(task_dir)
    age_hours = _dir_mtime_age_hours(task_dir)

    record = {
        "task_name": task_name,
        "task_dir": str(task_dir),
        "dir_mtime": dir_mtime,
    }

    if not result_file.is_file():
        # No result yet — running or timed out
        if age_hours > timeout_hours:
            record["status"] = "timeout"
        else:
            record["status"] = "running"
        record["reward"] = None
        record["error_fingerprint"] = None
        record["metrics"] = {}
        record["wall_clock_seconds"] = None
        return record

    # Parse result.json
    try:
        data = json.loads(result_file.read_text())
    except (json.JSONDecodeError, OSError):
        record["status"] = "errored"
        record["reward"] = None
        record["error_fingerprint"] = {
            "fingerprint_id": "result_json_corrupt",
            "label": "Corrupt result.json",
            "severity": "infra",
            "advice": "Re-run the task; result.json is unreadable.",
            "matched_text": "",
        }
        record["metrics"] = {}
        record["wall_clock_seconds"] = None
        return record

    # Check for exception
    exception_info = data.get("exception_info")
    reward = _extract_reward(data)
    tokens = _extract_tokens(data)
    wall_clock = data.get("wall_clock_seconds")

    record["reward"] = reward
    record["metrics"] = {k: v for k, v in tokens.items() if v is not None}
    record["wall_clock_seconds"] = wall_clock

    # Extract timestamps
    record["started_at"] = data.get("started_at", "")
    record["finished_at"] = data.get("finished_at", "")

    if exception_info is not None:
        record["status"] = "errored"
        record["error_fingerprint"] = fingerprint_error(exception_info)
    elif reward is not None and reward > 0:
        record["status"] = "completed_pass"
        record["error_fingerprint"] = None
    else:
        record["status"] = "completed_fail"
        record["error_fingerprint"] = None

    return record


def scan_all_tasks(
    timeout_hours: float,
    suite_filter: str | None = None,
    config_filter: str | None = None,
    since_minutes: int | None = None,
    failures_only: bool = False,
) -> dict:
    """Scan runs/official/ and classify all tasks.

    Returns the full output structure ready for JSON serialization.
    """
    tasks = []
    totals = defaultdict(int)
    by_suite = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    error_summary = defaultdict(lambda: {"count": 0, "label": "", "severity": ""})

    if not RUNS_DIR.exists():
        return _build_output(tasks, totals, by_suite, error_summary)

    now = time.time()
    since_cutoff = None
    if since_minutes is not None:
        since_cutoff = now - (since_minutes * 60)

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        if should_skip(run_dir.name):
            continue

        suite = detect_suite(run_dir.name)
        if suite is None:
            continue
        if suite_filter and suite != suite_filter:
            continue

        for config in CONFIGS:
            if config_filter and config != config_filter:
                continue

            config_path = run_dir / config
            if not config_path.is_dir():
                continue

            # Walk the config dir for task directories
            for task_dir in _iter_task_dirs(config_path):
                # Apply --since filter
                if since_cutoff is not None:
                    try:
                        mtime = task_dir.stat().st_mtime
                        if mtime < since_cutoff:
                            continue
                    except OSError:
                        continue

                record = classify_task(task_dir, timeout_hours)
                record["suite"] = suite
                record["config"] = config

                # Apply --failures-only filter
                if failures_only and record["status"] in ("completed_pass",):
                    continue

                tasks.append(record)
                totals[record["status"]] += 1
                by_suite[suite][config][record["status"]] += 1

                # Accumulate error summary
                fp = record.get("error_fingerprint")
                if fp:
                    fp_id = fp["fingerprint_id"]
                    error_summary[fp_id]["count"] += 1
                    error_summary[fp_id]["label"] = fp["label"]
                    error_summary[fp_id]["severity"] = fp["severity"]

    return _build_output(tasks, totals, by_suite, error_summary)


def _iter_task_dirs(config_path: Path):
    """Yield task directories under a config path.

    Handles both layouts:
    - config_path/batch_timestamp/task_name__hash/
    - config_path/task_name__hash/
    """
    if not config_path.is_dir():
        return

    for entry in sorted(config_path.iterdir()):
        if not entry.is_dir():
            continue

        # Skip archived/broken subdirectories at any level
        if should_skip(entry.name):
            continue

        # Check if this is a batch timestamp dir (starts with "20")
        if entry.name.startswith("20"):
            # Timestamp batch dir — task dirs are inside
            for trial_dir in sorted(entry.iterdir()):
                if trial_dir.is_dir() and not trial_dir.name.startswith("20") and not should_skip(trial_dir.name):
                    yield trial_dir
        elif "__" in entry.name:
            # Direct task dir (task_name__hash)
            yield entry


def _build_output(tasks, totals, by_suite, error_summary) -> dict:
    """Assemble the final output dict."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": dict(totals),
        "by_suite": {
            suite: {
                config: dict(statuses)
                for config, statuses in configs.items()
            }
            for suite, configs in sorted(by_suite.items())
        },
        "error_summary": dict(error_summary),
        "tasks": tasks,
    }


# ---------------------------------------------------------------------------
# Write per-task status.json
# ---------------------------------------------------------------------------

def write_task_status_files(output: dict):
    """Write a status.json alongside each task's result.json."""
    for task in output["tasks"]:
        task_dir = Path(task["task_dir"])
        if not task_dir.is_dir():
            continue

        status_data = {
            "task_name": task["task_name"],
            "suite": task.get("suite", ""),
            "config": task.get("config", ""),
            "status": task["status"],
            "started_at": task.get("started_at", ""),
            "finished_at": task.get("finished_at", ""),
            "wall_clock_seconds": task.get("wall_clock_seconds"),
            "reward": task.get("reward"),
            "error_summary": task.get("error_fingerprint"),
            "metrics": task.get("metrics", {}),
            "log_tail": _read_log_tail(task_dir),
            "generated_at": output["generated_at"],
        }

        status_path = task_dir / "status.json"
        try:
            status_path.write_text(json.dumps(status_data, indent=2) + "\n")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Table output
# ---------------------------------------------------------------------------

def format_table(output: dict) -> str:
    """Format output as compact ASCII tables."""
    lines = []
    gen = output["generated_at"]
    lines.append(f"Benchmark Status Report  (generated: {gen})")
    lines.append("")

    # Totals
    totals = output["totals"]
    total_all = sum(totals.values())
    lines.append(f"TOTALS: {total_all} tasks")
    for status in ("running", "completed_pass", "completed_fail", "errored", "timeout"):
        count = totals.get(status, 0)
        if count:
            lines.append(f"  {status:20s} {count:>5d}")
    lines.append("")

    # By suite/config breakdown
    by_suite = output["by_suite"]
    if by_suite:
        # Header
        configs_present = set()
        for configs in by_suite.values():
            configs_present.update(configs.keys())
        configs_sorted = [c for c in CONFIGS if c in configs_present]

        header = f"{'Suite':25s}"
        for cfg in configs_sorted:
            short = cfg.replace("sourcegraph_", "SG_")
            header += f" | {short:>18s}"
        lines.append(header)
        lines.append("-" * len(header))

        for suite in sorted(by_suite.keys()):
            row = f"{suite:25s}"
            for cfg in configs_sorted:
                statuses = by_suite[suite].get(cfg, {})
                p = statuses.get("completed_pass", 0)
                f_ = statuses.get("completed_fail", 0)
                e = statuses.get("errored", 0)
                r = statuses.get("running", 0)
                t = statuses.get("timeout", 0)
                total = p + f_ + e + r + t
                cell = f"{p}/{total}"
                if e:
                    cell += f" ({e}err)"
                if r:
                    cell += f" ({r}run)"
                row += f" | {cell:>18s}"
            lines.append(row)
        lines.append("")

    # Error summary
    error_summary = output["error_summary"]
    if error_summary:
        lines.append("ERROR SUMMARY:")
        for fp_id, info in sorted(error_summary.items(), key=lambda x: -x[1]["count"]):
            lines.append(f"  {info['count']:>3d}x  [{info['severity']:>8s}]  {fp_id}: {info['label']}")
        lines.append("")

    # Task details (only non-pass or if few tasks)
    non_pass = [t for t in output["tasks"] if t["status"] != "completed_pass"]
    if non_pass:
        lines.append(f"NON-PASSING TASKS ({len(non_pass)}):")
        for t in non_pass:
            fp_str = ""
            if t.get("error_fingerprint"):
                fp_str = f" [{t['error_fingerprint']['fingerprint_id']}]"
            reward_str = f" reward={t['reward']:.2f}" if t["reward"] is not None else ""
            lines.append(f"  {t['status']:16s}  {t.get('suite',''):20s}  {t.get('config',''):18s}  {t['task_name']}{reward_str}{fp_str}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Scan benchmark runs and report aggregate status."
    )
    parser.add_argument(
        "--format", choices=["json", "table"], default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--failures-only", action="store_true",
        help="Only show errored, failed, and timeout tasks",
    )
    parser.add_argument(
        "--since", type=int, default=None, metavar="N",
        help="Only tasks modified in the last N minutes",
    )
    parser.add_argument(
        "--suite", default=None,
        help="Filter to one benchmark suite (e.g., ccb_pytorch)",
    )
    parser.add_argument(
        "--config", default=None,
        help="Filter to one config (baseline, sourcegraph_base, sourcegraph_full)",
    )
    parser.add_argument(
        "--timeout-hours", type=float, default=4.0,
        help="Hours without result.json before marking as timeout (default: 4)",
    )
    parser.add_argument(
        "--write-status", action="store_true",
        help="Write per-task status.json files alongside result.json",
    )
    parser.add_argument(
        "--watch", action="store_true",
        help="Continuous re-scan mode",
    )
    parser.add_argument(
        "--interval", type=int, default=60,
        help="Seconds between scans in --watch mode (default: 60)",
    )
    return parser.parse_args()


def run_once(args) -> dict:
    """Execute a single scan and output results."""
    output = scan_all_tasks(
        timeout_hours=args.timeout_hours,
        suite_filter=args.suite,
        config_filter=args.config,
        since_minutes=args.since,
        failures_only=args.failures_only,
    )

    if args.write_status:
        write_task_status_files(output)

    return output


def main():
    args = parse_args()

    if args.watch:
        try:
            while True:
                # Clear screen for watch mode
                print("\033[2J\033[H", end="")
                output = run_once(args)
                if args.format == "table":
                    print(format_table(output))
                else:
                    print(json.dumps(output, indent=2))
                print(f"\n(refreshing every {args.interval}s — Ctrl+C to stop)")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        output = run_once(args)
        if args.format == "table":
            print(format_table(output))
        else:
            print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
