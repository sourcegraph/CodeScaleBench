#!/usr/bin/env python3
"""Comprehensive trace audit for CodeContextBench runs.

Scans all official runs, extracts per-task metadata, token counts, MCP tool
usage, Deep Search invocations, error patterns, and baseline contamination.
Produces both a structured JSON report and a human-readable summary.

Usage:
    # Human-readable summary (default)
    python3 scripts/audit_traces.py

    # JSON report to stdout
    python3 scripts/audit_traces.py --json

    # Verbose: include per-task detail rows in summary
    python3 scripts/audit_traces.py --verbose

    # Filter by suite or config
    python3 scripts/audit_traces.py --suite ccb_pytorch --config sourcegraph_full

    # Write JSON report to file
    python3 scripts/audit_traces.py --json --output audit_report.json
"""

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants (aligned with aggregate_status.py / generate_manifest.py)
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "runs" / "official"

SKIP_PATTERNS = ["__broken_verifier", "validation_test", "archive"]

DIR_PREFIX_TO_SUITE = {
    "bigcode_mcp_": "ccb_largerepo",
    "codereview_": "ccb_codereview",
    "crossrepo_": "ccb_crossrepo",
    "dependeval_": "ccb_dependeval",
    "dibench_": "ccb_dibench",
    "investigation_": "ccb_investigation",
    "k8s_docs_": "ccb_k8sdocs",
    "linuxflbench_": "ccb_linuxflbench",
    "locobench_": "ccb_locobench",
    "pytorch_": "ccb_pytorch",
    "repoqa_": "ccb_repoqa",
    "swebenchpro_": "ccb_swebenchpro",
    "sweperf_": "ccb_sweperf",
    "tac_": "ccb_tac",
}

CONFIGS = ["baseline", "sourcegraph_base", "sourcegraph_full"]

# Known MCP tool name patterns (the sg_ prefix is used in harbor transcripts).
# We match "name":"mcp__sourcegraph__sg_..." to count only actual tool_use
# invocations (not init listings or tool_result references).
MCP_TOOL_USE_RE = re.compile(r'"name"\s*:\s*"mcp__sourcegraph__(?:sg_)?(\w+)"')

# Fallback: any mention of mcp__sourcegraph (for init line detection)
MCP_TOOL_MENTION_RE = re.compile(r"mcp__sourcegraph__(?:sg_)?(\w+)")

# Deep Search tool — match deepsearch but NOT deepsearch_read
# Use the tool_use pattern for precision
DEEPSEARCH_USE_RE = re.compile(r'"name"\s*:\s*"mcp__sourcegraph__(?:sg_)?deepsearch"')
DEEPSEARCH_READ_USE_RE = re.compile(r'"name"\s*:\s*"mcp__sourcegraph__(?:sg_)?deepsearch_read"')

# Error patterns for setup stdout
SETUP_ERROR_PATTERNS = [
    re.compile(r"(?:Error|ERROR|error):\s+.+", re.IGNORECASE),
    re.compile(r"docker.*(?:build|pull).*fail", re.IGNORECASE),
    re.compile(r"COPY failed", re.IGNORECASE),
    re.compile(r"returned a non-zero code", re.IGNORECASE),
    re.compile(r"No such file or directory", re.IGNORECASE),
    re.compile(r"permission denied", re.IGNORECASE),
]

# Auth failure patterns in transcripts.
# These must be very specific to avoid false positives from code content
# in the transcript (the agent reads/writes source code containing words
# like "credentials", "token", "oauth" in normal code context).
AUTH_ERROR_PATTERNS = [
    # HTTP 401/403 status from API responses (not code content)
    re.compile(r'"status":\s*401\b'),
    re.compile(r'"status":\s*403\b'),
    re.compile(r'"error":\s*".*(?:unauthorized|forbidden|authentication failed).*"', re.IGNORECASE),
    # OAuth token refresh failures from Harbor/infrastructure
    re.compile(r"token refresh failed", re.IGNORECASE),
    re.compile(r"OAuth token.*(?:expired|invalid|revoked)", re.IGNORECASE),
    re.compile(r"credentials\.json.*(?:expired|invalid|error)", re.IGNORECASE),
    re.compile(r"ANTHROPIC_API_KEY.*(?:is invalid|has expired|authentication error)", re.IGNORECASE),
]

# MCP connection failure patterns in transcripts.
# Must avoid false positives from SG URLs, tool names, etc. in normal output.
MCP_ERROR_PATTERNS = [
    re.compile(r"McpError"),
    re.compile(r"MCP server.*(?:crash|exit|disconnect|failed to start)", re.IGNORECASE),
    re.compile(r"mcp_connection.*(?:error|refused|timeout|failed)", re.IGNORECASE),
    re.compile(r"Failed to connect to MCP", re.IGNORECASE),
    re.compile(r'"error":\s*".*MCP.*(?:connect|refused|unavailable).*"', re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def should_skip(dirname: str) -> bool:
    return any(pat in dirname for pat in SKIP_PATTERNS)


def detect_suite(dirname: str) -> Optional[str]:
    for prefix, suite in DIR_PREFIX_TO_SUITE.items():
        if dirname.startswith(prefix):
            return suite
    return None


def extract_task_name(dirname: str) -> str:
    """Strip __hash suffix from directory name to get task name."""
    parts = dirname.rsplit("__", 1)
    return parts[0] if len(parts) == 2 else dirname


def parse_iso_ts(ts_str: str) -> Optional[datetime]:
    """Parse an ISO timestamp string, handling common variants."""
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def wall_clock_seconds(started: str, finished: str) -> Optional[float]:
    """Compute wall clock duration in seconds from ISO timestamps."""
    s = parse_iso_ts(started)
    f = parse_iso_ts(finished)
    if s and f:
        return (f - s).total_seconds()
    return None


# ---------------------------------------------------------------------------
# Result.json extraction
# ---------------------------------------------------------------------------

def extract_result_info(result_path: Path) -> Optional[dict]:
    """Parse a task-level result.json and extract audit fields.

    Returns None if the file is unreadable or is a batch-level result.
    """
    try:
        data = json.loads(result_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    # Skip batch-level result.json (no task_name, only stats)
    if "task_name" not in data and "trial_name" not in data:
        return None

    # Source / suite
    source = data.get("source", "")

    # Exception info
    exception_info = data.get("exception_info")
    exception_type = None
    exception_message = None
    if exception_info is not None:
        if isinstance(exception_info, dict):
            exception_type = exception_info.get("exception_type",
                             exception_info.get("type", ""))
            exception_message = exception_info.get("exception_message",
                                exception_info.get("message", ""))
        elif isinstance(exception_info, str):
            exception_message = exception_info

    # Reward
    verifier = data.get("verifier_result") or {}
    rewards = verifier.get("rewards") or {}
    reward = rewards.get("reward")
    if reward is None:
        reward = rewards.get("score")
    reward_val = float(reward) if reward is not None else None

    # Status
    if exception_info is not None:
        status = "errored"
    elif reward_val is not None and reward_val > 0:
        status = "passed"
    else:
        status = "failed"

    # Tokens
    agent_result = data.get("agent_result") or {}
    n_input_tokens = agent_result.get("n_input_tokens")
    n_output_tokens = agent_result.get("n_output_tokens")
    n_cache_tokens = agent_result.get("n_cache_tokens",
                     agent_result.get("cache_creation_input_tokens"))

    # Timestamps
    started_at = data.get("started_at", "")
    finished_at = data.get("finished_at", "")
    wc = data.get("wall_clock_seconds")
    if wc is None:
        wc = wall_clock_seconds(started_at, finished_at)

    task_name = data.get("task_name", "")
    # Fallback: derive from directory name
    if not task_name:
        task_name = extract_task_name(result_path.parent.name)

    return {
        "task_name": task_name,
        "source": source,
        "status": status,
        "reward": reward_val,
        "exception_type": exception_type,
        "exception_message": exception_message,
        "has_exception": exception_info is not None,
        "n_input_tokens": n_input_tokens,
        "n_output_tokens": n_output_tokens,
        "n_cache_tokens": n_cache_tokens,
        "wall_clock_seconds": round(wc, 1) if wc is not None else None,
        "started_at": started_at,
        "finished_at": finished_at,
    }


# ---------------------------------------------------------------------------
# Transcript scanning (line-by-line for efficiency)
# ---------------------------------------------------------------------------

def scan_transcript(transcript_path: Path) -> dict:
    """Scan claude-code.txt line by line for MCP tool usage and error patterns.

    Returns a dict with:
      - mcp_tool_counts: Counter of tool_type -> count
      - mcp_total_calls: total MCP tool invocations
      - has_deepsearch: bool
      - deepsearch_count: int
      - deepsearch_read_count: int
      - auth_errors: list of matched patterns
      - mcp_errors: list of matched patterns
      - has_mcp_tools_available: bool (from init line)
    """
    result = {
        "mcp_tool_counts": Counter(),
        "mcp_total_calls": 0,
        "has_deepsearch": False,
        "deepsearch_count": 0,
        "deepsearch_read_count": 0,
        "auth_errors": [],
        "mcp_errors": [],
        "has_mcp_tools_available": False,
    }

    if not transcript_path.is_file():
        return result

    try:
        with open(transcript_path, "r", errors="replace") as f:
            for line_num, line in enumerate(f, 1):
                # Limit to first 500KB per line to avoid pathological cases
                if len(line) > 512_000:
                    line = line[:512_000]

                # Check init line for MCP tool availability
                if line_num == 1 and '"type":"system"' in line and '"init"' in line:
                    if "mcp__sourcegraph" in line:
                        result["has_mcp_tools_available"] = True
                    # Don't count init line tool listings as tool calls
                    continue

                # Count MCP tool calls — only "name":"mcp__sourcegraph__..." patterns
                # which appear in tool_use JSON, not in init listings or code content
                for m in MCP_TOOL_USE_RE.finditer(line):
                    tool_type = m.group(1)
                    result["mcp_tool_counts"][tool_type] += 1
                    result["mcp_total_calls"] += 1

                # Deep Search detection (tool_use pattern)
                ds_matches = DEEPSEARCH_USE_RE.findall(line)
                if ds_matches:
                    result["has_deepsearch"] = True
                    result["deepsearch_count"] += len(ds_matches)

                dsr_matches = DEEPSEARCH_READ_USE_RE.findall(line)
                if dsr_matches:
                    result["deepsearch_read_count"] += len(dsr_matches)

                # Auth error patterns — only check system/error lines, skip
                # tool_result lines (which contain code content that causes
                # false positives with words like "credentials", "token")
                is_tool_result = '"type":"tool_result"' in line
                if not is_tool_result and len(result["auth_errors"]) < 5:
                    for pat in AUTH_ERROR_PATTERNS:
                        m = pat.search(line)
                        if m:
                            result["auth_errors"].append(m.group(0)[:120])
                            break

                # MCP error patterns — same filtering as auth
                if not is_tool_result and len(result["mcp_errors"]) < 5:
                    for pat in MCP_ERROR_PATTERNS:
                        m = pat.search(line)
                        if m:
                            result["mcp_errors"].append(m.group(0)[:120])
                            break

    except OSError:
        pass

    return result


def scan_setup_stdout(task_dir: Path) -> list[str]:
    """Check agent/setup/stdout.txt for error patterns.

    Returns list of matched error strings (max 5).
    """
    stdout_path = task_dir / "agent" / "setup" / "stdout.txt"
    errors = []

    if not stdout_path.is_file():
        return errors

    try:
        with open(stdout_path, "r", errors="replace") as f:
            for line in f:
                if len(errors) >= 5:
                    break
                for pat in SETUP_ERROR_PATTERNS:
                    m = pat.search(line)
                    if m:
                        errors.append(m.group(0)[:200])
                        break
    except OSError:
        pass

    return errors


# Regex for tool calls in trajectory.json (function_name field)
TRAJECTORY_TOOL_RE = re.compile(r"mcp__sourcegraph__(?:sg_)?(\w+)")


def scan_trajectory(task_dir: Path) -> dict:
    """Scan trajectory.json for MCP tool usage.

    trajectory.json captures ALL tool calls including those from subagents
    (Task tool), which claude-code.txt may miss. This provides a more
    complete picture of MCP tool usage.

    Returns a dict with:
      - traj_mcp_tool_counts: Counter of tool_type -> count
      - traj_mcp_total_calls: total MCP tool invocations
      - traj_has_deepsearch: bool
      - traj_deepsearch_count: int
      - traj_deepsearch_read_count: int
    """
    result = {
        "traj_mcp_tool_counts": Counter(),
        "traj_mcp_total_calls": 0,
        "traj_has_deepsearch": False,
        "traj_deepsearch_count": 0,
        "traj_deepsearch_read_count": 0,
    }

    traj_path = task_dir / "agent" / "trajectory.json"
    if not traj_path.is_file():
        return result

    try:
        data = json.loads(traj_path.read_text())
    except (json.JSONDecodeError, OSError):
        return result

    steps = data.get("steps", [])
    for step in steps:
        # Check tool_calls list
        tool_calls = step.get("tool_calls", [])
        for tc in tool_calls:
            if not isinstance(tc, dict):
                continue
            fn_name = tc.get("function_name", "")
            m = TRAJECTORY_TOOL_RE.search(fn_name)
            if m:
                tool_type = m.group(1)
                result["traj_mcp_tool_counts"][tool_type] += 1
                result["traj_mcp_total_calls"] += 1

                if tool_type == "deepsearch":
                    result["traj_has_deepsearch"] = True
                    result["traj_deepsearch_count"] += 1
                elif tool_type == "deepsearch_read":
                    result["traj_deepsearch_read_count"] += 1

        # Also check the step message for "Executed mcp__sourcegraph__..." pattern
        # (trajectory sometimes records tool calls in message instead of tool_calls)
        msg = step.get("message", "")
        if isinstance(msg, str) and "mcp__sourcegraph" in msg:
            # Only count if no tool_calls were already found in this step
            if not tool_calls:
                for m in TRAJECTORY_TOOL_RE.finditer(msg):
                    tool_type = m.group(1)
                    result["traj_mcp_tool_counts"][tool_type] += 1
                    result["traj_mcp_total_calls"] += 1

                    if tool_type == "deepsearch":
                        result["traj_has_deepsearch"] = True
                        result["traj_deepsearch_count"] += 1
                    elif tool_type == "deepsearch_read":
                        result["traj_deepsearch_read_count"] += 1

    return result


# ---------------------------------------------------------------------------
# Directory walking
# ---------------------------------------------------------------------------

def iter_task_dirs(config_path: Path):
    """Yield (task_dir, batch_dir_name) for task directories under a config path.

    Handles both layouts:
    - config_path/batch_timestamp/task_name__hash/
    - config_path/task_name__hash/
    """
    if not config_path.is_dir():
        return

    for entry in sorted(config_path.iterdir()):
        if not entry.is_dir():
            continue
        if should_skip(entry.name):
            continue

        if entry.name.startswith("20"):
            # Timestamp batch dir
            for trial_dir in sorted(entry.iterdir()):
                if (trial_dir.is_dir()
                        and not trial_dir.name.startswith("20")
                        and not should_skip(trial_dir.name)):
                    yield trial_dir, entry.name
        elif "__" in entry.name:
            yield entry, ""


def collect_all_tasks(
    suite_filter: Optional[str] = None,
    config_filter: Optional[str] = None,
) -> list[dict]:
    """Walk runs/official/ and build a list of per-task audit records.

    Uses timestamp-based dedup: for duplicate (suite, config, task_name),
    keep the record with the latest started_at.
    """
    # Collect raw records keyed by (suite, config, task_name)
    best: dict[tuple[str, str, str], dict] = {}

    if not RUNS_DIR.exists():
        return []

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

            for task_dir, batch_name in iter_task_dirs(config_path):
                result_path = task_dir / "result.json"
                if not result_path.is_file():
                    continue

                info = extract_result_info(result_path)
                if info is None:
                    continue

                task_name = info["task_name"]
                # Shorter fallback from dirname
                if not task_name or len(task_name) > 200:
                    task_name = extract_task_name(task_dir.name)

                # Scan transcript for MCP usage and errors
                transcript_path = task_dir / "agent" / "claude-code.txt"
                transcript_info = scan_transcript(transcript_path)

                # Scan trajectory.json for complete MCP tool usage
                # (includes subagent calls that claude-code.txt may miss)
                traj_info = scan_trajectory(task_dir)

                # Merge: use trajectory data as primary for MCP tool counts
                # if trajectory has more calls (it captures subagent calls).
                # Use transcript data for error patterns (not in trajectory).
                if traj_info["traj_mcp_total_calls"] > transcript_info["mcp_total_calls"]:
                    mcp_tool_counts = dict(traj_info["traj_mcp_tool_counts"])
                    mcp_total_calls = traj_info["traj_mcp_total_calls"]
                    has_deepsearch = traj_info["traj_has_deepsearch"]
                    deepsearch_count = traj_info["traj_deepsearch_count"]
                    deepsearch_read_count = traj_info["traj_deepsearch_read_count"]
                    mcp_source = "trajectory"
                else:
                    mcp_tool_counts = dict(transcript_info["mcp_tool_counts"])
                    mcp_total_calls = transcript_info["mcp_total_calls"]
                    has_deepsearch = transcript_info["has_deepsearch"]
                    deepsearch_count = transcript_info["deepsearch_count"]
                    deepsearch_read_count = transcript_info["deepsearch_read_count"]
                    mcp_source = "transcript"

                # Scan setup stdout for Docker/build errors
                setup_errors = scan_setup_stdout(task_dir)

                record = {
                    "suite": suite,
                    "config": config,
                    "task_name": task_name,
                    "task_dir": str(task_dir),
                    "run_dir": run_dir.name,
                    "batch": batch_name,
                    **info,
                    # MCP usage (merged from transcript + trajectory)
                    "mcp_tool_counts": mcp_tool_counts,
                    "mcp_total_calls": mcp_total_calls,
                    "has_mcp_tools_available": transcript_info["has_mcp_tools_available"],
                    "has_deepsearch": has_deepsearch,
                    "deepsearch_count": deepsearch_count,
                    "deepsearch_read_count": deepsearch_read_count,
                    "mcp_source": mcp_source,
                    # Trajectory-specific counts (always included for comparison)
                    "traj_mcp_total_calls": traj_info["traj_mcp_total_calls"],
                    "transcript_mcp_total_calls": transcript_info["mcp_total_calls"],
                    # Error traces
                    "auth_errors_in_trace": transcript_info["auth_errors"],
                    "mcp_errors_in_trace": transcript_info["mcp_errors"],
                    "setup_errors": setup_errors,
                    "has_transcript": transcript_path.is_file(),
                    "has_trajectory": (task_dir / "agent" / "trajectory.json").is_file(),
                }

                # Timestamp-based dedup
                key = (suite, config, task_name)
                existing = best.get(key)
                if existing is None:
                    best[key] = record
                else:
                    new_ts = info.get("started_at", "")
                    old_ts = existing.get("started_at", "")
                    if new_ts >= old_ts:
                        best[key] = record

    return sorted(best.values(), key=lambda r: (r["suite"], r["config"], r["task_name"]))


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(tasks: list[dict]) -> dict:
    """Build the full audit report from collected task records."""

    # --- Overall totals ---
    total = len(tasks)
    status_counts = Counter(t["status"] for t in tasks)
    config_counts = Counter(t["config"] for t in tasks)
    suite_counts = Counter(t["suite"] for t in tasks)

    # --- Per-suite / per-config breakdown ---
    suite_config_matrix = defaultdict(lambda: defaultdict(lambda: {
        "total": 0, "passed": 0, "failed": 0, "errored": 0,
        "mean_reward": 0.0, "total_reward": 0.0,
        "mcp_total_calls": 0, "tasks_with_mcp": 0,
        "tasks_with_deepsearch": 0,
    }))

    for t in tasks:
        cell = suite_config_matrix[t["suite"]][t["config"]]
        cell["total"] += 1
        cell[t["status"]] += 1
        if t["reward"] is not None:
            cell["total_reward"] += t["reward"]
        if t["mcp_total_calls"] > 0:
            cell["tasks_with_mcp"] += 1
            cell["mcp_total_calls"] += t["mcp_total_calls"]
        if t["has_deepsearch"]:
            cell["tasks_with_deepsearch"] += 1

    # Compute means
    for suite_cells in suite_config_matrix.values():
        for cell in suite_cells.values():
            if cell["total"] > 0:
                cell["mean_reward"] = round(cell["total_reward"] / cell["total"], 4)
            del cell["total_reward"]

    # --- MCP tool usage aggregate ---
    mcp_tool_aggregate = Counter()
    for t in tasks:
        for tool, count in t.get("mcp_tool_counts", {}).items():
            mcp_tool_aggregate[tool] += count

    # --- Deep Search analysis (SG_full only) ---
    sg_full_tasks = [t for t in tasks if t["config"] == "sourcegraph_full"]
    ds_analysis = {
        "sg_full_total": len(sg_full_tasks),
        "sg_full_with_deepsearch": sum(1 for t in sg_full_tasks if t["has_deepsearch"]),
        "sg_full_without_deepsearch": sum(1 for t in sg_full_tasks if not t["has_deepsearch"]),
        "sg_full_no_deepsearch_tasks": [
            {"suite": t["suite"], "task_name": t["task_name"], "status": t["status"]}
            for t in sg_full_tasks if not t["has_deepsearch"]
        ],
    }
    if ds_analysis["sg_full_total"] > 0:
        ds_analysis["deepsearch_adoption_pct"] = round(
            100.0 * ds_analysis["sg_full_with_deepsearch"] / ds_analysis["sg_full_total"], 1
        )
    else:
        ds_analysis["deepsearch_adoption_pct"] = 0.0

    # --- Baseline contamination check ---
    baseline_tasks = [t for t in tasks if t["config"] == "baseline"]
    contaminated = [
        {
            "suite": t["suite"],
            "task_name": t["task_name"],
            "mcp_total_calls": t["mcp_total_calls"],
            "mcp_tool_counts": t["mcp_tool_counts"],
            "has_mcp_tools_available": t["has_mcp_tools_available"],
        }
        for t in baseline_tasks
        if t["mcp_total_calls"] > 0
    ]
    baseline_contamination = {
        "total_baseline_tasks": len(baseline_tasks),
        "contaminated_count": len(contaminated),
        "contaminated_tasks": contaminated,
    }

    # --- MCP availability check for SG configs ---
    sg_tasks = [t for t in tasks if t["config"] in ("sourcegraph_base", "sourcegraph_full")]
    sg_no_tools = [
        {
            "suite": t["suite"],
            "config": t["config"],
            "task_name": t["task_name"],
            "has_transcript": t["has_transcript"],
        }
        for t in sg_tasks
        if not t["has_mcp_tools_available"] and t["has_transcript"]
    ]
    mcp_availability = {
        "total_sg_tasks": len(sg_tasks),
        "sg_tasks_without_mcp_tools": len(sg_no_tools),
        "missing_mcp_tasks": sg_no_tools[:20],  # cap for readability
    }

    # --- Error pattern summary ---
    error_types = Counter()
    agent_setup_timeouts = []
    docker_build_failures = []
    auth_failures = []
    mcp_connection_failures = []
    tasks_with_setup_errors = []

    for t in tasks:
        if t["has_exception"]:
            etype = t.get("exception_type") or "unknown"
            error_types[etype] += 1

            if etype and "AgentSetupTimeoutError" in str(etype):
                agent_setup_timeouts.append({
                    "suite": t["suite"], "config": t["config"],
                    "task_name": t["task_name"],
                })
            if etype and "Docker" in str(etype):
                docker_build_failures.append({
                    "suite": t["suite"], "config": t["config"],
                    "task_name": t["task_name"],
                    "message": (t.get("exception_message") or "")[:200],
                })

        if t.get("auth_errors_in_trace"):
            auth_failures.append({
                "suite": t["suite"], "config": t["config"],
                "task_name": t["task_name"],
                "auth_errors": t["auth_errors_in_trace"],
            })

        if t.get("mcp_errors_in_trace"):
            mcp_connection_failures.append({
                "suite": t["suite"], "config": t["config"],
                "task_name": t["task_name"],
                "mcp_errors": t["mcp_errors_in_trace"],
            })

        if t.get("setup_errors"):
            tasks_with_setup_errors.append({
                "suite": t["suite"], "config": t["config"],
                "task_name": t["task_name"],
                "errors": t["setup_errors"],
            })

    # Also catch AgentSetupTimeoutError from exception_message
    for t in tasks:
        if t["has_exception"]:
            msg = t.get("exception_message") or ""
            etype = t.get("exception_type") or ""
            combined = f"{etype} {msg}"
            if "AgentSetupTimeout" in combined and not any(
                x["task_name"] == t["task_name"] and x["config"] == t["config"]
                for x in agent_setup_timeouts
            ):
                agent_setup_timeouts.append({
                    "suite": t["suite"], "config": t["config"],
                    "task_name": t["task_name"],
                })

    error_analysis = {
        "exception_type_counts": dict(error_types.most_common()),
        "agent_setup_timeouts": agent_setup_timeouts,
        "docker_build_failures": docker_build_failures,
        "auth_failures_in_traces": auth_failures,
        "mcp_connection_failures_in_traces": mcp_connection_failures,
        "tasks_with_setup_errors": tasks_with_setup_errors[:30],  # cap
    }

    # --- Token / cost summary ---
    token_stats = {
        "by_config": {},
        "by_suite": {},
    }
    for group_key, group_field in [("by_config", "config"), ("by_suite", "suite")]:
        buckets = defaultdict(lambda: {
            "count": 0, "total_input": 0, "total_output": 0, "total_cache": 0,
            "total_wall_seconds": 0.0, "wall_count": 0,
        })
        for t in tasks:
            gv = t[group_field]
            b = buckets[gv]
            b["count"] += 1
            if t["n_input_tokens"] is not None:
                b["total_input"] += t["n_input_tokens"]
            if t["n_output_tokens"] is not None:
                b["total_output"] += t["n_output_tokens"]
            if t["n_cache_tokens"] is not None:
                b["total_cache"] += t["n_cache_tokens"]
            if t["wall_clock_seconds"] is not None:
                b["total_wall_seconds"] += t["wall_clock_seconds"]
                b["wall_count"] += 1

        for gv, b in buckets.items():
            token_stats[group_key][gv] = {
                "task_count": b["count"],
                "total_input_tokens": b["total_input"],
                "total_output_tokens": b["total_output"],
                "total_cache_tokens": b["total_cache"],
                "avg_input_tokens": round(b["total_input"] / b["count"]) if b["count"] else 0,
                "avg_output_tokens": round(b["total_output"] / b["count"]) if b["count"] else 0,
                "avg_wall_seconds": round(b["total_wall_seconds"] / b["wall_count"], 1) if b["wall_count"] else 0.0,
            }

    # --- SG_base / SG_full tasks that never used MCP ---
    sg_no_mcp_usage = [
        {
            "suite": t["suite"], "config": t["config"],
            "task_name": t["task_name"],
            "status": t["status"],
            "has_mcp_tools_available": t["has_mcp_tools_available"],
        }
        for t in sg_tasks
        if t["mcp_total_calls"] == 0
    ]

    # --- Assemble full report ---
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scan_directory": str(RUNS_DIR),
        "summary": {
            "total_tasks": total,
            "status_counts": dict(status_counts),
            "config_counts": dict(config_counts),
            "suite_counts": dict(suite_counts),
        },
        "suite_config_matrix": {
            suite: dict(configs)
            for suite, configs in sorted(suite_config_matrix.items())
        },
        "mcp_tool_usage": {
            "aggregate_tool_counts": dict(mcp_tool_aggregate.most_common()),
            "total_mcp_invocations": sum(mcp_tool_aggregate.values()),
            "sg_tasks_never_used_mcp": {
                "count": len(sg_no_mcp_usage),
                "tasks": sg_no_mcp_usage[:30],  # cap for readability
            },
        },
        "deepsearch_analysis": ds_analysis,
        "baseline_contamination": baseline_contamination,
        "mcp_availability": mcp_availability,
        "error_analysis": error_analysis,
        "token_summary": token_stats,
        "tasks": tasks,
    }

    return report


# ---------------------------------------------------------------------------
# Human-readable summary
# ---------------------------------------------------------------------------

def format_summary(report: dict, verbose: bool = False) -> str:
    """Format the audit report as a human-readable text summary."""
    lines = []
    gen = report["generated_at"]
    lines.append(f"=== CodeContextBench Trace Audit Report ===")
    lines.append(f"Generated: {gen}")
    lines.append(f"Scan directory: {report['scan_directory']}")
    lines.append("")

    # --- Overall summary ---
    s = report["summary"]
    lines.append(f"OVERALL: {s['total_tasks']} tasks scanned")
    for status in ("passed", "failed", "errored"):
        count = s["status_counts"].get(status, 0)
        lines.append(f"  {status:12s}  {count:>5d}")
    lines.append("")

    lines.append("BY CONFIG:")
    for cfg in CONFIGS:
        count = s["config_counts"].get(cfg, 0)
        short = cfg.replace("sourcegraph_", "SG_")
        lines.append(f"  {short:18s}  {count:>5d}")
    lines.append("")

    # --- Suite x Config matrix ---
    matrix = report["suite_config_matrix"]
    if matrix:
        lines.append("SUITE x CONFIG MATRIX:")
        header = f"  {'Suite':25s}"
        for cfg in CONFIGS:
            short = cfg.replace("sourcegraph_", "SG_")
            header += f" | {short:>20s}"
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))

        for suite in sorted(matrix.keys()):
            row = f"  {suite:25s}"
            for cfg in CONFIGS:
                cell = matrix[suite].get(cfg)
                if cell:
                    p = cell.get("passed", 0)
                    t = cell.get("total", 0)
                    mr = cell.get("mean_reward", 0.0)
                    mcp = cell.get("tasks_with_mcp", 0)
                    cell_str = f"{p}/{t} r={mr:.3f} mcp={mcp}"
                else:
                    cell_str = "-"
                row += f" | {cell_str:>20s}"
            lines.append(row)
        lines.append("")

    # --- MCP tool usage ---
    mcp = report["mcp_tool_usage"]
    lines.append(f"MCP TOOL USAGE: {mcp['total_mcp_invocations']} total invocations")
    agg = mcp["aggregate_tool_counts"]
    if agg:
        for tool, count in sorted(agg.items(), key=lambda x: -x[1]):
            lines.append(f"  {tool:30s}  {count:>6d}")
    else:
        lines.append("  (none)")
    lines.append("")

    no_mcp = mcp["sg_tasks_never_used_mcp"]
    if no_mcp["count"] > 0:
        lines.append(f"SG TASKS THAT NEVER USED MCP: {no_mcp['count']}")
        for t in no_mcp["tasks"][:10]:
            lines.append(f"  {t['suite']:20s}  {t['config']:18s}  {t['task_name']:40s}  {t['status']}")
        if no_mcp["count"] > 10:
            lines.append(f"  ... and {no_mcp['count'] - 10} more")
        lines.append("")

    # --- Deep Search analysis ---
    ds = report["deepsearch_analysis"]
    lines.append(f"DEEP SEARCH ANALYSIS (SG_full only):")
    lines.append(f"  Total SG_full tasks:       {ds['sg_full_total']}")
    lines.append(f"  With Deep Search:          {ds['sg_full_with_deepsearch']} ({ds['deepsearch_adoption_pct']:.1f}%)")
    lines.append(f"  Without Deep Search:       {ds['sg_full_without_deepsearch']}")
    if ds["sg_full_no_deepsearch_tasks"]:
        lines.append("  Tasks missing Deep Search:")
        for t in ds["sg_full_no_deepsearch_tasks"][:15]:
            lines.append(f"    {t['suite']:20s}  {t['task_name']:40s}  {t['status']}")
        if len(ds["sg_full_no_deepsearch_tasks"]) > 15:
            lines.append(f"    ... and {len(ds['sg_full_no_deepsearch_tasks']) - 15} more")
    lines.append("")

    # --- Baseline contamination ---
    bc = report["baseline_contamination"]
    lines.append(f"BASELINE CONTAMINATION CHECK:")
    lines.append(f"  Total baseline tasks:  {bc['total_baseline_tasks']}")
    lines.append(f"  Contaminated (MCP):    {bc['contaminated_count']}")
    if bc["contaminated_tasks"]:
        lines.append("  Contaminated tasks:")
        for t in bc["contaminated_tasks"][:10]:
            lines.append(f"    {t['suite']:20s}  {t['task_name']:40s}  calls={t['mcp_total_calls']}")
        if len(bc["contaminated_tasks"]) > 10:
            lines.append(f"    ... and {len(bc['contaminated_tasks']) - 10} more")
    lines.append("")

    # --- MCP availability ---
    ma = report["mcp_availability"]
    if ma["sg_tasks_without_mcp_tools"] > 0:
        lines.append(f"MCP AVAILABILITY ISSUES:")
        lines.append(f"  SG tasks without MCP tools in init: {ma['sg_tasks_without_mcp_tools']} / {ma['total_sg_tasks']}")
        for t in ma["missing_mcp_tasks"][:10]:
            lines.append(f"    {t['suite']:20s}  {t['config']:18s}  {t['task_name']}")
        lines.append("")

    # --- Error analysis ---
    ea = report["error_analysis"]
    exc_counts = ea["exception_type_counts"]
    if exc_counts:
        lines.append("EXCEPTION TYPES:")
        for etype, count in sorted(exc_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {count:>4d}x  {etype}")
        lines.append("")

    if ea["agent_setup_timeouts"]:
        lines.append(f"AGENT SETUP TIMEOUTS: {len(ea['agent_setup_timeouts'])}")
        for t in ea["agent_setup_timeouts"]:
            lines.append(f"  {t['suite']:20s}  {t['config']:18s}  {t['task_name']}")
        lines.append("")

    if ea["docker_build_failures"]:
        lines.append(f"DOCKER BUILD FAILURES: {len(ea['docker_build_failures'])}")
        for t in ea["docker_build_failures"]:
            lines.append(f"  {t['suite']:20s}  {t['config']:18s}  {t['task_name']}")
            if t.get("message"):
                lines.append(f"    {t['message'][:120]}")
        lines.append("")

    if ea["auth_failures_in_traces"]:
        lines.append(f"AUTH FAILURES IN TRACES: {len(ea['auth_failures_in_traces'])}")
        for t in ea["auth_failures_in_traces"][:10]:
            lines.append(f"  {t['suite']:20s}  {t['config']:18s}  {t['task_name']}")
            for err in t["auth_errors"][:2]:
                lines.append(f"    {err}")
        lines.append("")

    if ea["mcp_connection_failures_in_traces"]:
        lines.append(f"MCP CONNECTION FAILURES IN TRACES: {len(ea['mcp_connection_failures_in_traces'])}")
        for t in ea["mcp_connection_failures_in_traces"][:10]:
            lines.append(f"  {t['suite']:20s}  {t['config']:18s}  {t['task_name']}")
            for err in t["mcp_errors"][:2]:
                lines.append(f"    {err}")
        lines.append("")

    if ea["tasks_with_setup_errors"]:
        lines.append(f"TASKS WITH SETUP ERRORS: {len(ea['tasks_with_setup_errors'])}")
        for t in ea["tasks_with_setup_errors"][:10]:
            lines.append(f"  {t['suite']:20s}  {t['config']:18s}  {t['task_name']}")
            for err in t["errors"][:2]:
                lines.append(f"    {err[:120]}")
        if len(ea["tasks_with_setup_errors"]) > 10:
            lines.append(f"  ... and {len(ea['tasks_with_setup_errors']) - 10} more")
        lines.append("")

    # --- Token summary ---
    ts = report["token_summary"]
    lines.append("TOKEN SUMMARY BY CONFIG:")
    for cfg in CONFIGS:
        info = ts["by_config"].get(cfg)
        if info:
            short = cfg.replace("sourcegraph_", "SG_")
            lines.append(f"  {short:18s}  tasks={info['task_count']:>4d}  "
                         f"avg_in={info['avg_input_tokens']:>10,}  "
                         f"avg_out={info['avg_output_tokens']:>8,}  "
                         f"avg_wall={info['avg_wall_seconds']:>7.0f}s")
    lines.append("")

    lines.append("TOKEN SUMMARY BY SUITE:")
    for suite in sorted(ts["by_suite"].keys()):
        info = ts["by_suite"][suite]
        lines.append(f"  {suite:25s}  tasks={info['task_count']:>4d}  "
                     f"avg_in={info['avg_input_tokens']:>10,}  "
                     f"avg_out={info['avg_output_tokens']:>8,}  "
                     f"avg_wall={info['avg_wall_seconds']:>7.0f}s")
    lines.append("")

    # --- Verbose: per-task details ---
    if verbose:
        lines.append("=" * 120)
        lines.append("PER-TASK DETAILS:")
        lines.append(f"{'Suite':20s}  {'Config':18s}  {'Task':40s}  {'Status':8s}  {'Reward':>7s}  {'MCP':>5s}  {'DS':>3s}  {'Wall(s)':>8s}")
        lines.append("-" * 120)
        for t in report["tasks"]:
            reward_str = f"{t['reward']:.3f}" if t["reward"] is not None else "  N/A"
            mcp_str = str(t["mcp_total_calls"])
            ds_str = "Y" if t["has_deepsearch"] else "N"
            wall_str = f"{t['wall_clock_seconds']:.0f}" if t["wall_clock_seconds"] is not None else "N/A"
            lines.append(
                f"{t['suite']:20s}  {t['config']:18s}  "
                f"{t['task_name'][:40]:40s}  {t['status']:8s}  "
                f"{reward_str:>7s}  {mcp_str:>5s}  {ds_str:>3s}  {wall_str:>8s}"
            )
            # Show errors if any
            if verbose and t["has_exception"]:
                etype = t.get("exception_type") or ""
                emsg = (t.get("exception_message") or "")[:100]
                lines.append(f"    EXCEPTION: {etype}: {emsg}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Audit all official benchmark run traces for quality issues."
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output full report as JSON (default: human-readable summary)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Include per-task detail rows in human-readable summary",
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
        "--output", default=None,
        help="Write output to file instead of stdout",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    t0 = time.monotonic()
    tasks = collect_all_tasks(
        suite_filter=args.suite,
        config_filter=args.config,
    )
    elapsed_collect = time.monotonic() - t0

    t1 = time.monotonic()
    report = generate_report(tasks)
    elapsed_report = time.monotonic() - t1

    report["timing"] = {
        "collect_seconds": round(elapsed_collect, 2),
        "report_seconds": round(elapsed_report, 2),
        "total_seconds": round(elapsed_collect + elapsed_report, 2),
    }

    if args.json:
        output_text = json.dumps(report, indent=2, default=str)
    else:
        output_text = format_summary(report, verbose=args.verbose)
        output_text += f"\n[Scan completed in {report['timing']['total_seconds']:.1f}s]\n"

    if args.output:
        Path(args.output).write_text(output_text)
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(output_text)


if __name__ == "__main__":
    main()
