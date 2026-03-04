#!/usr/bin/env python3
"""Post-task validation: flags issues (crashes, MCP tools not used, anomalies).

Usage:
    # Validate all tasks in a jobs directory
    python3 scripts/validate_task_run.py --jobs-dir <dir> --config <mode>

    # Validate a single task directory
    python3 scripts/validate_task_run.py --task-dir <dir> --config <mode>

Exit codes:
    0  Clean (no issues or INFO only)
    1  CRITICAL issues found
    2  WARNING issues found (no CRITICAL)
"""

import argparse
import json
import glob
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config_utils import is_mcp_config

# ANSI color codes
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

SEVERITY_COLORS = {
    "CRITICAL": RED,
    "WARNING": YELLOW,
    "INFO": CYAN,
}

# Configs that use MCP tools (uses is_mcp_config() for new names)
MCP_CONFIGS = {"sourcegraph_full", "mcp-remote-direct", "mcp-remote-artifact", "artifact_full"}


@dataclass
class Flag:
    rule: str
    severity: str  # CRITICAL, WARNING, INFO
    message: str
    task_id: str
    task_dir: str


def load_task_data(task_dir: str) -> Optional[dict]:
    """Load task_metrics.json, falling back to result.json for crash fields."""
    metrics_path = os.path.join(task_dir, "task_metrics.json")
    result_path = os.path.join(task_dir, "result.json")

    data = {}

    # Primary source: task_metrics.json
    if os.path.isfile(metrics_path):
        with open(metrics_path) as f:
            data = json.load(f)

    # Fallback/supplement from result.json for fields not in task_metrics
    if os.path.isfile(result_path):
        try:
            with open(result_path) as f:
                result = json.load(f)
            # Extract crash-related fields not in task_metrics.json
            if "exception_info" not in data:
                data["_exception_info"] = result.get("exception_info")
            if "agent_result" not in data:
                data["_agent_result"] = result.get("agent_result")
            if "task_name" not in data and "task_id" not in data:
                data["task_id"] = result.get("task_name", os.path.basename(task_dir.rstrip("/")))
        except (json.JSONDecodeError, OSError):
            pass

    if not data:
        return None

    # Ensure task_id is set
    if "task_id" not in data:
        data["task_id"] = os.path.basename(task_dir.rstrip("/"))

    return data


def validate_task(data: dict, task_dir: str, config: str) -> List[Flag]:
    """Run all validation rules against a single task's data."""
    flags = []
    task_id = data.get("task_id", "unknown")

    def flag(rule: str, severity: str, message: str):
        flags.append(Flag(
            rule=rule,
            severity=severity,
            message=message,
            task_id=task_id,
            task_dir=task_dir,
        ))

    # --- CRITICAL rules ---

    # status_error: status == "error"
    status = data.get("status")
    if status == "error":
        flag("status_error", "CRITICAL", f"Task status is 'error'")

    # exception_raised: exception_info != null
    exception_info = data.get("_exception_info")
    if exception_info is not None:
        exc_type = ""
        if isinstance(exception_info, dict):
            exc_type = exception_info.get("type", "")
        elif isinstance(exception_info, str):
            exc_type = exception_info[:80]
        flag("exception_raised", "CRITICAL", f"Exception raised: {exc_type}")

    # agent_never_ran: agent_result == null
    agent_result = data.get("_agent_result")
    if agent_result is None:
        # Only flag if we actually loaded result.json (i.e., we have the field)
        if "_agent_result" in data:
            flag("agent_never_ran", "CRITICAL", "Agent never ran (agent_result is null)")

    # task_crashed: "[CRASHED]" in task_name
    if "[CRASHED]" in task_id:
        flag("task_crashed", "CRITICAL", "Task name contains [CRASHED]")

    # mcp_never_used: tool_calls_mcp == 0 in MCP modes
    if is_mcp_config(config):
        mcp_calls = data.get("tool_calls_mcp")
        if mcp_calls is not None and mcp_calls == 0:
            flag("mcp_never_used", "CRITICAL",
                 "MCP tools were never called in MCP-enabled mode")

    # --- WARNING rules ---

    # deepsearch_unused: search_calls_deepsearch == 0 in MCP direct modes
    if config in ("sourcegraph_full", "mcp-remote-direct"):
        ds_calls = data.get("search_calls_deepsearch")
        if ds_calls is not None and ds_calls == 0:
            flag("deepsearch_unused", "WARNING",
                 "Deep Search was never used in MCP mode")

    # barely_tried: low reward with very few or unmeasured tool calls
    reward = data.get("reward")
    total_calls = data.get("tool_calls_total")
    if reward is not None and reward < 0.1:
        if total_calls is None or total_calls < 3:
            calls_str = str(total_calls) if total_calls is not None else "null"
            flag("barely_tried", "WARNING",
                 f"Low reward ({reward}) with minimal/unmeasured tool calls ({calls_str})")

    # metrics_extraction_failed: all token/tool metrics null despite task completing
    input_tokens = data.get("input_tokens")
    output_tokens = data.get("output_tokens")
    files_modified = data.get("files_modified")
    if (input_tokens is None and output_tokens is None
            and total_calls is None and files_modified is None
            and status not in ("error",)):
        flag("metrics_extraction_failed", "WARNING",
             "All metrics are null — metric extraction may have failed")

    # suspiciously_fast: wall_clock_seconds < 10 (non-crash)
    wall_clock = data.get("wall_clock_seconds")
    is_crash = status == "error" or "[CRASHED]" in task_id
    if wall_clock is not None and wall_clock < 10 and not is_crash:
        flag("suspiciously_fast", "WARNING",
             f"Task completed in {wall_clock:.1f}s (suspiciously fast)")

    # no_output_tokens: output_tokens == 0 or < 50
    if output_tokens is not None and output_tokens < 50:
        flag("no_output_tokens", "WARNING",
             f"Output tokens very low: {output_tokens}")

    # --- INFO rules ---

    # mcp_ratio_report: report mcp_ratio value for MCP modes
    if is_mcp_config(config):
        mcp_ratio = data.get("mcp_ratio")
        if mcp_ratio is not None:
            flag("mcp_ratio_report", "INFO",
                 f"MCP ratio: {mcp_ratio:.2%}")

    return flags


def discover_task_dirs(jobs_dir: str) -> List[str]:
    """Find task directories via jobs_dir/*/*/ glob (same as extract_all_metrics)."""
    pattern = os.path.join(jobs_dir, "*", "*", "")
    dirs = sorted(glob.glob(pattern))
    # Only include directories that have at least result.json or task_metrics.json
    return [
        d for d in dirs
        if os.path.isfile(os.path.join(d, "task_metrics.json"))
        or os.path.isfile(os.path.join(d, "result.json"))
    ]


def print_summary(all_flags: List[Flag]):
    """Print colored summary to stdout (CRITICAL and WARNING only)."""
    console_flags = [f for f in all_flags if f.severity in ("CRITICAL", "WARNING")]
    if not console_flags:
        print(f"{BOLD}Validation: all tasks clean{RESET}")
        return

    # Group by severity
    by_severity = {}
    for f in console_flags:
        by_severity.setdefault(f.severity, []).append(f)

    for severity in ("CRITICAL", "WARNING"):
        items = by_severity.get(severity, [])
        if not items:
            continue
        color = SEVERITY_COLORS[severity]
        print(f"\n{color}{BOLD}  {severity} ({len(items)}):{RESET}")
        for f in items:
            print(f"{color}    [{f.rule}] {f.task_id}: {f.message}{RESET}")


def main():
    parser = argparse.ArgumentParser(
        description="Post-task validation: flags crashes, MCP issues, and anomalies."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--jobs-dir", help="Validate all tasks in a jobs directory")
    group.add_argument("--task-dir", help="Validate a single task directory")
    parser.add_argument("--config", required=True,
                        help="Config mode (baseline, sourcegraph_full)")
    args = parser.parse_args()

    # Discover task directories
    if args.task_dir:
        task_dirs = [args.task_dir]
        output_dir = args.task_dir
    else:
        task_dirs = discover_task_dirs(args.jobs_dir)
        output_dir = args.jobs_dir

    if not task_dirs:
        print(f"No task directories found in {output_dir}")
        sys.exit(0)

    # Validate each task
    all_flags: List[Flag] = []
    tasks_checked = 0

    for td in task_dirs:
        data = load_task_data(td)
        if data is None:
            continue
        tasks_checked += 1
        flags = validate_task(data, td, args.config)
        all_flags.extend(flags)

        # Write per-task flagged.json (only if there are flags for this task)
        if flags:
            task_flag_path = os.path.join(td, "flagged.json")
            with open(task_flag_path, "w") as f:
                json.dump([asdict(fl) for fl in flags], f, indent=2)

    # Write flagged_tasks.json at the jobs-dir / task-dir level
    output_path = os.path.join(output_dir, "flagged_tasks.json")
    output_data = {
        "config": args.config,
        "tasks_checked": tasks_checked,
        "total_flags": len(all_flags),
        "critical_count": sum(1 for f in all_flags if f.severity == "CRITICAL"),
        "warning_count": sum(1 for f in all_flags if f.severity == "WARNING"),
        "info_count": sum(1 for f in all_flags if f.severity == "INFO"),
        "flags": [asdict(f) for f in all_flags],
    }
    with open(output_path, "w") as f:
        json.dump(output_data, f, indent=2)

    # Print console summary
    print(f"\nValidation: checked {tasks_checked} tasks, "
          f"{output_data['critical_count']} critical, "
          f"{output_data['warning_count']} warnings")
    print_summary(all_flags)
    print(f"  Details: {output_path}")

    # Exit code
    if output_data["critical_count"] > 0:
        sys.exit(1)
    elif output_data["warning_count"] > 0:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
