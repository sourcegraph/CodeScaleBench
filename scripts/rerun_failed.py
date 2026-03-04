#!/usr/bin/env python3
"""Rerun failed benchmark tasks, optionally filtering by error fingerprint.

Generates harbor run commands for failed tasks from the most recent runs.

Usage:
    # List all failed tasks as rerun commands
    python3 scripts/rerun_failed.py

    # Filter by error fingerprint
    python3 scripts/rerun_failed.py --filter token_refresh_403

    # Filter by suite
    python3 scripts/rerun_failed.py --suite ccb_pytorch

    # Filter by config
    python3 scripts/rerun_failed.py --config baseline

    # Actually execute the reruns (not just print)
    python3 scripts/rerun_failed.py --filter token_refresh_403 --execute

    # Dry-run (default): just print the commands
    python3 scripts/rerun_failed.py --filter token_refresh_403 --dry-run
"""

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aggregate_status import scan_all_tasks, CONFIGS

# Map suite names to benchmark directory prefixes
SUITE_TO_BENCHMARK_DIR = {
    "ccb_largerepo": "ccb_largerepo",
    "ccb_crossrepo": "ccb_crossrepo",
    "ccb_dibench": "ccb_dibench",
    "ccb_k8sdocs": "ccb_k8sdocs",
    "ccb_locobench": "ccb_locobench",
    "ccb_pytorch": "ccb_pytorch",
    "ccb_repoqa": "ccb_repoqa",
    "ccb_swebenchpro": "ccb_swebenchpro",
    "ccb_sweperf": "ccb_sweperf",
    "ccb_tac": "ccb_tac",
}

CONFIG_TO_MCP_TYPE = {
    "baseline": "none",
    "sourcegraph_full": "deepsearch",
}

AGENT_PATH = "agents.claude_baseline_agent:BaselineClaudeCodeAgent"
DEFAULT_MODEL = "anthropic/claude-opus-4-5-20251101"


def find_benchmark_path(suite: str, task_name: str) -> str | None:
    """Find the benchmark definition path for a task."""
    bench_dir = SUITE_TO_BENCHMARK_DIR.get(suite)
    if not bench_dir:
        return None

    base = Path(__file__).resolve().parent.parent / "benchmarks" / bench_dir
    if not base.is_dir():
        return None

    # Direct match
    task_path = base / task_name
    if task_path.is_dir():
        return str(task_path)

    # For swebenchpro, tasks are under tasks/ subdir
    task_path = base / "tasks" / task_name
    if task_path.is_dir():
        return str(task_path)

    return None


def generate_rerun_command(task: dict, model: str = DEFAULT_MODEL) -> str | None:
    """Generate a harbor run command for a failed task."""
    suite = task.get("suite", "")
    config = task.get("config", "")
    task_name = task.get("task_name", "")

    bench_path = find_benchmark_path(suite, task_name)
    if bench_path is None:
        return None

    mcp_type = CONFIG_TO_MCP_TYPE.get(config, "none")

    # Derive jobs-dir from the original task_dir
    # task_dir is like: runs/official/<run_dir>/<config>/<batch>/<task__hash>
    # We want: runs/official/<run_dir>/<config>
    task_dir = Path(task.get("task_dir", ""))
    # Walk up to find the config dir
    jobs_dir = None
    for parent in task_dir.parents:
        if parent.name in CONFIGS:
            jobs_dir = str(parent)
            break

    if jobs_dir is None:
        jobs_dir = f"runs/official/rerun/{config}"

    cmd = (
        f"BASELINE_MCP_TYPE={mcp_type} harbor run "
        f"--path {bench_path} "
        f"--agent-import-path {AGENT_PATH} "
        f"--model {model} "
        f"--jobs-dir {jobs_dir} "
        f"-n 1"
    )
    return cmd


def main():
    parser = argparse.ArgumentParser(
        description="Generate rerun commands for failed benchmark tasks."
    )
    parser.add_argument(
        "--filter", default=None,
        help="Filter by error fingerprint ID (e.g., token_refresh_403)",
    )
    parser.add_argument(
        "--suite", default=None,
        help="Filter by benchmark suite",
    )
    parser.add_argument(
        "--config", default=None,
        help="Filter by config (baseline, sourcegraph_full)",
    )
    parser.add_argument(
        "--status", default=None,
        help="Filter by status (errored, completed_fail, timeout). Default: all non-pass.",
    )
    parser.add_argument(
        "--model", default=DEFAULT_MODEL,
        help=f"Model to use for reruns (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually execute the rerun commands (default: dry-run)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Print commands without executing (default)",
    )
    args = parser.parse_args()

    # If --execute is set, disable dry-run
    if args.execute:
        args.dry_run = False

    # Scan for all tasks
    output = scan_all_tasks(
        timeout_hours=4.0,
        suite_filter=args.suite,
        config_filter=args.config,
        failures_only=True,
    )

    failed_tasks = output["tasks"]

    # Apply status filter
    if args.status:
        failed_tasks = [t for t in failed_tasks if t["status"] == args.status]

    # Apply fingerprint filter
    if args.filter:
        filtered = []
        for t in failed_tasks:
            fp = t.get("error_fingerprint")
            if fp and fp.get("fingerprint_id") == args.filter:
                filtered.append(t)
        failed_tasks = filtered

    if not failed_tasks:
        print("No matching failed tasks found.")
        return

    print(f"Found {len(failed_tasks)} failed tasks to rerun:")
    print()

    commands = []
    for task in failed_tasks:
        cmd = generate_rerun_command(task, model=args.model)
        if cmd is None:
            print(f"  SKIP (no benchmark path): {task['suite']}/{task['config']}/{task['task_name']}")
            continue

        fp_str = ""
        fp = task.get("error_fingerprint")
        if fp:
            fp_str = f" [{fp['fingerprint_id']}]"

        print(f"  {task['suite']}/{task['config']}/{task['task_name']}{fp_str}")
        print(f"    {cmd}")
        print()
        commands.append(cmd)

    if not commands:
        print("No rerun commands generated.")
        return

    if args.dry_run:
        print(f"Dry-run: {len(commands)} commands generated. Use --execute to run them.")
        print()
        print("# Copy-paste all commands:")
        for cmd in commands:
            print(cmd)
    else:
        print(f"Executing {len(commands)} rerun commands...")
        for i, cmd in enumerate(commands, 1):
            print(f"\n--- Rerun {i}/{len(commands)} ---")
            print(f"$ {cmd}")
            result = subprocess.run(cmd, shell=True, cwd=str(Path(__file__).resolve().parent.parent))
            if result.returncode != 0:
                print(f"WARNING: Command exited with code {result.returncode}")


if __name__ == "__main__":
    main()
