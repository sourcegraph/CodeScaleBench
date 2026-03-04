#!/usr/bin/env python3
"""Workflow metrics extraction engine for CodeScaleBench enterprise metrics.

Extracts per-task workflow-level metrics from existing trace data in runs/official/,
maps tasks to workflow categories, computes time savings and navigation reduction
per workflow category.

All time projections are MODELED ESTIMATES. See docs/WORKFLOW_METRICS.md for methodology.

Usage:
    python3 scripts/workflow_metrics.py
    python3 scripts/workflow_metrics.py --help
    python3 scripts/workflow_metrics.py --suite ccb_pytorch --config baseline
    python3 scripts/workflow_metrics.py --output workflow_metrics.json
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Ensure scripts/ is on path for sibling imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from aggregate_status import (
    RUNS_DIR,
    CONFIGS,
    should_skip,
    detect_suite,
    _iter_task_dirs,
    _extract_task_name,
)
from workflow_taxonomy import WORKFLOW_CATEGORIES, SUITE_TO_CATEGORY

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Tool names used to identify navigation vs editing
_READ_TOOLS = {"Read"}
_SEARCH_TOOLS = {"Grep", "Glob", "WebSearch"}
_EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}
_MCP_SEARCH_SUFFIXES = ("sg_keyword_search", "sg_nls_search", "sg_deepsearch",
                         "sg_read_file", "sg_find_references", "sg_go_to_definition",
                         "sg_list_files", "sg_compare_revisions", "sg_commit_search",
                         "sg_diff_search")


def _is_mcp_tool(name: str) -> bool:
    return name.startswith("mcp__")


def _is_navigation_tool(name: str) -> bool:
    """Return True if tool is a navigation/search/read tool (not editing)."""
    if name in _READ_TOOLS or name in _SEARCH_TOOLS:
        return True
    if _is_mcp_tool(name):
        return True
    return False


# ---------------------------------------------------------------------------
# Per-task metric extraction
# ---------------------------------------------------------------------------

def _extract_agent_task_time(result_data: dict) -> Optional[float]:
    """Extract agent task time in seconds from result.json.

    Uses agent_execution timestamps (coding + tool use, excludes Docker build + verifier).
    Falls back to wall_clock if agent_execution not available.
    """
    agent_exec = result_data.get("agent_execution") or {}
    started = agent_exec.get("started_at")
    finished = agent_exec.get("finished_at")
    if started and finished:
        try:
            s = datetime.fromisoformat(started.replace("Z", "+00:00"))
            e = datetime.fromisoformat(finished.replace("Z", "+00:00"))
            return (e - s).total_seconds()
        except (ValueError, TypeError):
            pass

    # Fallback to overall wall clock
    overall_start = result_data.get("started_at")
    overall_end = result_data.get("finished_at")
    if overall_start and overall_end:
        try:
            s = datetime.fromisoformat(overall_start.replace("Z", "+00:00"))
            e = datetime.fromisoformat(overall_end.replace("Z", "+00:00"))
            return (e - s).total_seconds()
        except (ValueError, TypeError):
            pass
    return None


def _extract_reward(data: dict) -> Optional[float]:
    """Extract reward from result.json data."""
    verifier = data.get("verifier_result") or {}
    rewards = verifier.get("rewards") or {}
    for key in ("reward", "score"):
        if key in rewards:
            try:
                return float(rewards[key])
            except (TypeError, ValueError):
                continue
    return None


def _extract_tool_counts_from_transcript(transcript_path: Path) -> dict[str, int]:
    """Parse claude-code.txt JSONL to count tool calls by name."""
    counts: dict[str, int] = {}
    if not transcript_path.is_file():
        return counts
    try:
        text = transcript_path.read_text(errors="replace")
    except OSError:
        return counts

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message") or {}
        content = message.get("content") or []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = block.get("name")
                if name:
                    counts[name] = counts.get(name, 0) + 1
    return counts


def _extract_tool_counts_from_trajectory(trajectory_path: Path) -> dict[str, int]:
    """Parse trajectory.json to count tool calls by name."""
    counts: dict[str, int] = {}
    if not trajectory_path.is_file():
        return counts
    try:
        data = json.loads(trajectory_path.read_text())
    except (OSError, json.JSONDecodeError):
        return counts

    for step in data.get("steps") or []:
        for tc in step.get("tool_calls") or []:
            name = tc.get("function_name")
            if name:
                counts[name] = counts.get(name, 0) + 1
    return counts


def _count_context_switches_from_transcript(transcript_path: Path) -> int:
    """Count transitions between distinct files in tool calls.

    A context switch = agent operates on a different file than the previous
    file-targeting tool call.
    """
    if not transcript_path.is_file():
        return 0
    try:
        text = transcript_path.read_text(errors="replace")
    except OSError:
        return 0

    switches = 0
    last_file: Optional[str] = None

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message") or {}
        content = message.get("content") or []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name") or ""
            inp = block.get("input") or {}
            # Extract file path from common tool inputs
            fp = inp.get("file_path") or inp.get("path")
            if not fp and name == "Bash":
                continue  # Skip bash — file target ambiguous
            if not fp:
                continue
            if last_file is not None and fp != last_file:
                switches += 1
            last_file = fp
    return switches


def _count_context_switches_from_trajectory(trajectory_path: Path) -> int:
    """Count file context switches from trajectory.json."""
    if not trajectory_path.is_file():
        return 0
    try:
        data = json.loads(trajectory_path.read_text())
    except (OSError, json.JSONDecodeError):
        return 0

    switches = 0
    last_file: Optional[str] = None

    for step in data.get("steps") or []:
        for tc in step.get("tool_calls") or []:
            name = tc.get("function_name") or ""
            args = tc.get("arguments") or {}
            fp = args.get("file_path") or args.get("path")
            if not fp and name == "Bash":
                continue
            if not fp:
                continue
            if last_file is not None and fp != last_file:
                switches += 1
            last_file = fp
    return switches


def _count_unique_files_from_transcript(transcript_path: Path) -> int:
    """Count unique files accessed from claude-code.txt."""
    if not transcript_path.is_file():
        return 0
    try:
        text = transcript_path.read_text(errors="replace")
    except OSError:
        return 0

    files: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message") or {}
        content = message.get("content") or []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            inp = block.get("input") or {}
            fp = inp.get("file_path") or inp.get("path")
            if fp:
                files.add(fp)
    return len(files)


def _count_unique_files_from_trajectory(trajectory_path: Path) -> int:
    """Count unique files accessed from trajectory.json."""
    if not trajectory_path.is_file():
        return 0
    try:
        data = json.loads(trajectory_path.read_text())
    except (OSError, json.JSONDecodeError):
        return 0

    files: set[str] = set()
    for step in data.get("steps") or []:
        for tc in step.get("tool_calls") or []:
            args = tc.get("arguments") or {}
            fp = args.get("file_path") or args.get("path")
            if fp:
                files.add(fp)
    return len(files)


def extract_task_workflow_metrics(task_dir: Path, suite: str, config: str) -> Optional[dict]:
    """Extract workflow-level metrics for a single task.

    Returns a dict with all per-task workflow metrics, or None if
    the task directory lacks a result.json.
    """
    result_path = task_dir / "result.json"
    if not result_path.is_file():
        return None

    try:
        result_data = json.loads(result_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    # Skip batch-level result.json
    if "n_total_trials" in result_data and "task_name" not in result_data:
        return None

    task_name = _extract_task_name(task_dir.name)
    trajectory_path = task_dir / "agent" / "trajectory.json"
    transcript_path = task_dir / "agent" / "claude-code.txt"

    # Agent task time
    agent_task_time = _extract_agent_task_time(result_data)

    # Reward
    reward = _extract_reward(result_data)

    # Tool counts — prefer transcript (includes subagent calls)
    tool_counts = _extract_tool_counts_from_transcript(transcript_path)
    if not tool_counts:
        tool_counts = _extract_tool_counts_from_trajectory(trajectory_path)

    tool_call_count = sum(tool_counts.values())
    file_read_count = tool_counts.get("Read", 0)
    file_edit_count = sum(tool_counts.get(t, 0) for t in _EDIT_TOOLS)
    search_query_count = (
        tool_counts.get("Grep", 0)
        + tool_counts.get("Glob", 0)
    )
    # Add MCP search tools
    mcp_call_count = sum(c for name, c in tool_counts.items() if _is_mcp_tool(name))

    # Unique files accessed
    unique_files = _count_unique_files_from_transcript(transcript_path)
    if unique_files == 0:
        unique_files = _count_unique_files_from_trajectory(trajectory_path)

    # Navigation ratio
    nav_calls = sum(c for name, c in tool_counts.items() if _is_navigation_tool(name))
    navigation_ratio = nav_calls / tool_call_count if tool_call_count > 0 else 0.0

    # Context switches
    context_switch_count = _count_context_switches_from_transcript(transcript_path)
    if context_switch_count == 0 and trajectory_path.is_file():
        context_switch_count = _count_context_switches_from_trajectory(trajectory_path)

    # Workflow category
    workflow_category = SUITE_TO_CATEGORY.get(suite)

    return {
        "task_name": task_name,
        "suite": suite,
        "config": config,
        "workflow_category": workflow_category,
        "reward": reward,
        "agent_task_time_seconds": agent_task_time,
        "tool_call_count": tool_call_count,
        "file_read_count": file_read_count,
        "file_edit_count": file_edit_count,
        "search_query_count": search_query_count,
        "mcp_call_count": mcp_call_count,
        "unique_files_accessed": unique_files,
        "navigation_ratio": round(navigation_ratio, 4) if navigation_ratio else 0.0,
        "context_switch_count": context_switch_count,
    }


# ---------------------------------------------------------------------------
# Scanning & dedup
# ---------------------------------------------------------------------------

def scan_workflow_metrics(
    suite_filter: Optional[str] = None,
    config_filter: Optional[str] = None,
) -> list[dict]:
    """Scan runs/official/ and extract workflow metrics for all tasks.

    Uses timestamp-based dedup: for duplicate (suite, config, task_name),
    keeps the latest started_at.
    """
    if not RUNS_DIR.exists():
        logger.warning("runs/official/ not found: %s", RUNS_DIR)
        return []

    # Collect all task records, then dedup
    raw_records: list[tuple[str, dict]] = []  # (started_at, record)

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir() or should_skip(run_dir.name):
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

            for task_dir in _iter_task_dirs(config_path):
                record = extract_task_workflow_metrics(task_dir, suite, config)
                if record is None:
                    continue

                # Get started_at for dedup
                started_at = ""
                result_path = task_dir / "result.json"
                try:
                    rdata = json.loads(result_path.read_text())
                    started_at = rdata.get("started_at", "")
                except (OSError, json.JSONDecodeError):
                    pass

                raw_records.append((started_at, record))

    # Timestamp-based dedup: latest wins
    best: dict[tuple[str, str, str], tuple[str, dict]] = {}
    for started_at, rec in raw_records:
        key = (rec["suite"], rec["config"], rec["task_name"])
        existing = best.get(key)
        if existing is None or started_at > existing[0]:
            best[key] = (started_at, rec)

    return [rec for _, rec in best.values()]


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _safe_mean(values: list[float]) -> Optional[float]:
    """Mean of non-None values, or None."""
    filtered = [v for v in values if v is not None]
    return statistics.mean(filtered) if filtered else None


def _safe_median(values: list[float]) -> Optional[float]:
    """Median of non-None values, or None."""
    filtered = [v for v in values if v is not None]
    return statistics.median(filtered) if filtered else None


def compute_category_aggregates(tasks: list[dict]) -> dict[str, dict]:
    """Compute per-workflow-category aggregates grouped by config.

    Returns {category: {config: {mean_time, median_time, mean_nav_ratio, ...}}}.
    """
    # Group by (category, config)
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in tasks:
        cat = t.get("workflow_category")
        if cat is None:
            continue
        grouped[(cat, t["config"])].append(t)

    result: dict[str, dict] = {}
    for (cat, config), cat_tasks in sorted(grouped.items()):
        if cat not in result:
            result[cat] = {
                "description": WORKFLOW_CATEGORIES.get(cat, {}).get("description", ""),
                "suites": WORKFLOW_CATEGORIES.get(cat, {}).get("benchmark_suites", []),
                "configs": {},
            }

        times = [t["agent_task_time_seconds"] for t in cat_tasks if t["agent_task_time_seconds"] is not None]
        tool_counts = [t["tool_call_count"] for t in cat_tasks if t["tool_call_count"] > 0]
        nav_ratios = [t["navigation_ratio"] for t in cat_tasks]

        result[cat]["configs"][config] = {
            "n_tasks": len(cat_tasks),
            "mean_agent_task_time_seconds": round(_safe_mean(times), 2) if _safe_mean(times) is not None else None,
            "median_agent_task_time_seconds": round(_safe_median(times), 2) if _safe_median(times) is not None else None,
            "mean_navigation_ratio": round(_safe_mean(nav_ratios), 4) if _safe_mean(nav_ratios) is not None else None,
            "mean_tool_calls": round(_safe_mean(tool_counts), 1) if _safe_mean(tool_counts) is not None else None,
        }

    return result


def compute_category_deltas(category_aggregates: dict[str, dict]) -> dict[str, dict]:
    """Compute per-category delta: baseline_mean_time - sg_full_mean_time.

    Returns {category: {estimated_time_saved_seconds, engineer_equivalent_minutes}}.
    """
    deltas: dict[str, dict] = {}
    for cat, cat_data in category_aggregates.items():
        configs = cat_data.get("configs", {})
        bl = configs.get("baseline", {})
        sg = configs.get("sourcegraph_full", {})

        bl_time = bl.get("mean_agent_task_time_seconds")
        sg_time = sg.get("mean_agent_task_time_seconds")

        estimated_saved: Optional[float] = None
        engineer_minutes: Optional[float] = None
        pct_change: Optional[float] = None

        if bl_time is not None and sg_time is not None:
            estimated_saved = round(bl_time - sg_time, 2)
            if bl_time > 0:
                pct_change = round((estimated_saved / bl_time) * 100, 1)

            # Convert to engineer-equivalent using taxonomy multipliers
            cat_info = WORKFLOW_CATEGORIES.get(cat, {})
            tok_per_min = cat_info.get("time_multiplier_tokens_per_minute", 800.0)
            # Engineer-equivalent: if agent saved X seconds, that maps to
            # X seconds of engineer time * a scaling factor.
            # The multiplier represents how fast an engineer processes tokens;
            # we use agent_task_time directly as a proxy for engineer time
            # since the agent is doing the same work the engineer would.
            engineer_minutes = round(estimated_saved / 60.0, 2)

        deltas[cat] = {
            "baseline_mean_time_seconds": bl_time,
            "sg_full_mean_time_seconds": sg_time,
            "estimated_time_saved_seconds": estimated_saved,
            "estimated_time_saved_pct": pct_change,
            "engineer_equivalent_minutes_saved": engineer_minutes,
            "note": "modeled estimate — see docs/WORKFLOW_METRICS.md for methodology",
        }

    return deltas


def compute_navigation_summary(tasks: list[dict]) -> dict[str, dict]:
    """Compute overall navigation metrics grouped by config.

    Returns {config: {mean_nav_ratio, mean_search_count, mean_mcp_calls, ...}}.
    """
    grouped: dict[str, list[dict]] = defaultdict(list)
    for t in tasks:
        grouped[t["config"]].append(t)

    result: dict[str, dict] = {}
    for config, config_tasks in sorted(grouped.items()):
        nav_ratios = [t["navigation_ratio"] for t in config_tasks]
        search_counts = [t["search_query_count"] for t in config_tasks]
        mcp_counts = [t["mcp_call_count"] for t in config_tasks]
        ctx_switches = [t["context_switch_count"] for t in config_tasks]
        unique_files = [t["unique_files_accessed"] for t in config_tasks]

        result[config] = {
            "n_tasks": len(config_tasks),
            "mean_navigation_ratio": round(_safe_mean(nav_ratios), 4) if _safe_mean(nav_ratios) is not None else None,
            "mean_search_query_count": round(_safe_mean(search_counts), 1) if _safe_mean(search_counts) is not None else None,
            "mean_mcp_call_count": round(_safe_mean(mcp_counts), 1) if _safe_mean(mcp_counts) is not None else None,
            "mean_context_switch_count": round(_safe_mean(ctx_switches), 1) if _safe_mean(ctx_switches) is not None else None,
            "mean_unique_files_accessed": round(_safe_mean(unique_files), 1) if _safe_mean(unique_files) is not None else None,
        }

    return result


# ---------------------------------------------------------------------------
# Output assembly
# ---------------------------------------------------------------------------

def build_output(
    tasks: list[dict],
    category_aggregates: dict[str, dict],
    category_deltas: dict[str, dict],
    navigation_summary: dict[str, dict],
) -> dict:
    """Assemble the full workflow_metrics.json output."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology": (
            "All time projections are MODELED ESTIMATES based on agent task execution times. "
            "Time savings are computed as baseline_mean_time - sg_full_mean_time per workflow "
            "category. Engineer-equivalent minutes use the delta directly (1:1 agent-to-engineer "
            "time mapping) as a conservative lower bound. See docs/WORKFLOW_METRICS.md."
        ),
        "per_task": tasks,
        "per_category": category_aggregates,
        "category_deltas": category_deltas,
        "navigation_summary": navigation_summary,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract workflow-level metrics from benchmark trace data."
    )
    parser.add_argument(
        "--suite", default=None,
        help="Filter to one benchmark suite (e.g., ccb_pytorch)",
    )
    parser.add_argument(
        "--config", default=None,
        help="Filter to one config (baseline, sourcegraph_full)",
    )
    parser.add_argument(
        "--output", default=None, metavar="FILE",
        help="Write JSON output to FILE (default: stdout)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    # Scan
    tasks = scan_workflow_metrics(
        suite_filter=args.suite,
        config_filter=args.config,
    )

    if not tasks:
        logger.warning("No tasks found in %s", RUNS_DIR)

    # Aggregate
    category_aggregates = compute_category_aggregates(tasks)
    category_deltas = compute_category_deltas(category_aggregates)
    navigation_summary = compute_navigation_summary(tasks)

    # Build output
    output = build_output(tasks, category_aggregates, category_deltas, navigation_summary)

    # Write
    json_str = json.dumps(output, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json_str + "\n")
        print(f"Wrote {len(tasks)} task records to {args.output}")
    else:
        print(json_str)


if __name__ == "__main__":
    main()
