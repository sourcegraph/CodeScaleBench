"""Extract metrics from Harbor result.json and related files.

All extractors handle missing/malformed files gracefully by returning None
for missing fields. Stdlib only — no external dependencies.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import TaskMetrics


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp, returning None on failure."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _seconds_between(start: Optional[str], end: Optional[str]) -> Optional[float]:
    """Return seconds between two ISO timestamps, or None."""
    s = _parse_iso(start)
    e = _parse_iso(end)
    if s is None or e is None:
        return None
    return (e - s).total_seconds()


def extract_task_from_result_json(
    result_json_path: str | Path,
    benchmark: str = "",
    config_name: str = "",
) -> TaskMetrics:
    """Read a Harbor result.json and populate a TaskMetrics.

    Args:
        result_json_path: Path to a result.json file.
        benchmark: Benchmark name to set on the TaskMetrics.
        config_name: Config name to set on the TaskMetrics.

    Returns:
        A TaskMetrics with fields populated from result.json.
        Missing/malformed data yields None for individual fields.
    """
    path = Path(result_json_path)
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return TaskMetrics(
            task_id="unknown",
            benchmark=benchmark,
            config_name=config_name,
            status="error",
        )

    # Task ID
    task_name = data.get("task_name", "unknown")

    # Reward
    reward = None
    verifier_result = data.get("verifier_result") or {}
    rewards = verifier_result.get("rewards") or {}
    if "reward" in rewards:
        try:
            reward = float(rewards["reward"])
        except (TypeError, ValueError):
            pass

    # Status
    if data.get("exception_info"):
        status = "error"
    elif reward is not None:
        status = "passed" if reward > 0 else "failed"
    else:
        status = "unknown"

    # Tokens and cost from agent_result
    agent_result = data.get("agent_result") or {}
    input_tokens = agent_result.get("n_input_tokens")
    output_tokens = agent_result.get("n_output_tokens")
    cache_tokens = agent_result.get("n_cache_tokens")
    cost_usd = agent_result.get("cost_usd")

    # Cast to correct types if present
    if input_tokens is not None:
        try:
            input_tokens = int(input_tokens)
        except (TypeError, ValueError):
            input_tokens = None
    if output_tokens is not None:
        try:
            output_tokens = int(output_tokens)
        except (TypeError, ValueError):
            output_tokens = None
    if cache_tokens is not None:
        try:
            cache_tokens = int(cache_tokens)
        except (TypeError, ValueError):
            cache_tokens = None
    if cost_usd is not None:
        try:
            cost_usd = float(cost_usd)
        except (TypeError, ValueError):
            cost_usd = None

    # Timing
    wall_clock = _seconds_between(
        data.get("started_at"), data.get("finished_at")
    )

    agent_exec = data.get("agent_execution") or {}
    agent_execution_seconds = _seconds_between(
        agent_exec.get("started_at"), agent_exec.get("finished_at")
    )

    env_setup = data.get("environment_setup") or {}
    environment_setup_seconds = _seconds_between(
        env_setup.get("started_at"), env_setup.get("finished_at")
    )

    verifier_section = data.get("verifier") or {}
    verifier_seconds = _seconds_between(
        verifier_section.get("started_at"), verifier_section.get("finished_at")
    )

    return TaskMetrics(
        task_id=task_name,
        benchmark=benchmark,
        config_name=config_name,
        reward=reward,
        status=status,
        wall_clock_seconds=wall_clock,
        agent_execution_seconds=agent_execution_seconds,
        environment_setup_seconds=environment_setup_seconds,
        verifier_seconds=verifier_seconds,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_tokens,  # result.json only has n_cache_tokens
        cost_usd=cost_usd,
    )


def extract_task_tokens_from_transcript(
    claude_code_txt_path: str | Path,
) -> dict:
    """Parse claude-code.txt JSONL to extract token usage from the final result entry.

    Fallback when result.json lacks token data.

    Args:
        claude_code_txt_path: Path to the agent/claude-code.txt JSONL file.

    Returns:
        Dict with keys: input_tokens, output_tokens,
        cache_creation_input_tokens, cache_read_input_tokens,
        total_cost_usd. Missing values are None.
    """
    empty = {
        "input_tokens": None,
        "output_tokens": None,
        "cache_creation_input_tokens": None,
        "cache_read_input_tokens": None,
        "total_cost_usd": None,
    }
    path = Path(claude_code_txt_path)
    if not path.is_file():
        return empty

    # Read lines in reverse to find the last result entry efficiently
    last_result = None
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return empty

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") == "result":
            last_result = entry
            break

    if last_result is None:
        return empty

    usage = last_result.get("usage") or {}
    return {
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_creation_input_tokens": usage.get("cache_creation_input_tokens"),
        "cache_read_input_tokens": usage.get("cache_read_input_tokens"),
        "total_cost_usd": last_result.get("total_cost_usd"),
    }


def extract_swebench_partial_score(
    test_stdout_path: str | Path,
) -> Optional[float]:
    """Parse verifier/test-stdout.txt for SWE-Bench partial score.

    Looks for lines like:
        Required tests: N
        Required tests that passed: M
    Returns M/N as partial_score.

    Args:
        test_stdout_path: Path to verifier/test-stdout.txt.

    Returns:
        Float partial score (0.0-1.0), or None if not parseable.
    """
    path = Path(test_stdout_path)
    if not path.is_file():
        return None

    try:
        text = path.read_text()
    except OSError:
        return None

    required_match = re.search(r"Required tests:\s*(\d+)", text)
    passed_match = re.search(r"Required tests that passed:\s*(\d+)", text)

    if not required_match or not passed_match:
        return None

    required = int(required_match.group(1))
    passed = int(passed_match.group(1))

    if required == 0:
        return None

    return passed / required


def _empty_tool_usage() -> dict:
    """Return a dict with all tool usage fields set to None."""
    return {
        "tool_calls_total": None,
        "tool_calls_mcp": None,
        "tool_calls_local": None,
        "tool_calls_by_name": None,
        "mcp_ratio": None,
    }


# Tools bundled with Claude Code (non-MCP)
_LOCAL_TOOLS = {
    "Bash", "Read", "Edit", "Write", "Grep", "Glob",
    "Task", "TaskOutput", "TodoWrite", "WebFetch", "WebSearch",
    "NotebookEdit", "AskUserQuestion", "EnterPlanMode", "ExitPlanMode",
    "Skill", "TaskStop", "ToolSearch",
}


def _is_mcp_tool(name: str) -> bool:
    """Return True if the tool name indicates an MCP tool (mcp__ prefix)."""
    return name.startswith("mcp__")


def _build_tool_usage_dict(tool_counts: dict[str, int]) -> dict:
    """Build the standard tool usage dict from a {name: count} mapping."""
    if not tool_counts:
        return _empty_tool_usage()

    total = sum(tool_counts.values())
    mcp = sum(c for name, c in tool_counts.items() if _is_mcp_tool(name))
    local = sum(c for name, c in tool_counts.items() if name in _LOCAL_TOOLS)

    return {
        "tool_calls_total": total,
        "tool_calls_mcp": mcp,
        "tool_calls_local": local,
        "tool_calls_by_name": dict(tool_counts),
        "mcp_ratio": mcp / total if total > 0 else 0.0,
    }


def extract_tool_usage_from_trajectory(
    trajectory_json_path: str | Path,
) -> dict:
    """Parse ATIF v1.2 trajectory.json to extract tool usage counts.

    Iterates steps[].tool_calls[].function_name and categorises each tool
    as MCP (mcp__* prefix) or local (Bash, Read, Edit, etc.).

    Args:
        trajectory_json_path: Path to the agent/trajectory.json file.

    Returns:
        Dict with keys: tool_calls_total, tool_calls_mcp, tool_calls_local,
        tool_calls_by_name (Counter dict), mcp_ratio (mcp/total).
        Returns None-valued dict if file is missing or unparseable.
    """
    path = Path(trajectory_json_path)
    if not path.is_file():
        return _empty_tool_usage()

    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return _empty_tool_usage()

    tool_counts: dict[str, int] = {}
    steps = data.get("steps") or []
    for step in steps:
        tool_calls = step.get("tool_calls") or []
        for tc in tool_calls:
            name = tc.get("function_name")
            if name:
                tool_counts[name] = tool_counts.get(name, 0) + 1

    return _build_tool_usage_dict(tool_counts)


def extract_tool_usage_from_transcript(
    claude_code_txt_path: str | Path,
) -> dict:
    """Parse JSONL claude-code.txt to extract tool usage counts.

    Fallback when trajectory.json is missing. Finds entries with
    type='assistant' that have tool_use content blocks and counts tool names.

    Args:
        claude_code_txt_path: Path to the agent/claude-code.txt JSONL file.

    Returns:
        Dict with keys: tool_calls_total, tool_calls_mcp, tool_calls_local,
        tool_calls_by_name (Counter dict), mcp_ratio (mcp/total).
        Returns None-valued dict if file is missing or unparseable.
    """
    path = Path(claude_code_txt_path)
    if not path.is_file():
        return _empty_tool_usage()

    try:
        lines = path.read_text().splitlines()
    except OSError:
        return _empty_tool_usage()

    tool_counts: dict[str, int] = {}
    for line in lines:
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
                    tool_counts[name] = tool_counts.get(name, 0) + 1

    return _build_tool_usage_dict(tool_counts)


def extract_reward_from_file(
    reward_txt_path: str | Path,
) -> Optional[float]:
    """Read a reward.txt file and return the float value.

    Fallback for when reward is not in result.json.

    Args:
        reward_txt_path: Path to verifier/reward.txt.

    Returns:
        Float reward value, or None if file missing/unparseable.
    """
    path = Path(reward_txt_path)
    if not path.is_file():
        return None

    try:
        text = path.read_text().strip()
        return float(text)
    except (OSError, ValueError):
        return None
