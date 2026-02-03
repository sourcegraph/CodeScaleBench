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


def extract_run_config(
    batch_dir: str | Path,
    transcript_path: Optional[str | Path] = None,
) -> dict:
    """Extract harness configuration from a batch directory.

    Reads config.json from the batch directory and optionally parses the
    system init line from claude-code.txt to capture runtime details.

    Args:
        batch_dir: Path to the batch timestamp directory containing config.json.
        transcript_path: Optional path to agent/claude-code.txt for init data.

    Returns:
        Dict with keys: model_name, agent_import_path, timeout_multiplier,
        mcp_mode, task_source, claude_code_version, permission_mode,
        tools, mcp_servers, model. Missing values are None.
    """
    result: dict = {
        "model_name": None,
        "agent_import_path": None,
        "timeout_multiplier": None,
        "mcp_mode": None,
        "task_source": None,
        "claude_code_version": None,
        "permission_mode": None,
        "tools": None,
        "mcp_servers": None,
        "model": None,
    }

    batch_dir = Path(batch_dir)
    config_path = batch_dir / "config.json"

    # --- Extract from config.json ---
    if config_path.is_file():
        try:
            data = json.loads(config_path.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}

        # Batch-level config has "agents" (list); task-level has "agent" (dict)
        agents = data.get("agents") or []
        agent = data.get("agent") or {}
        if agents and isinstance(agents, list):
            agent = agents[0]
        result["model_name"] = agent.get("model_name")
        result["agent_import_path"] = agent.get("import_path")
        result["timeout_multiplier"] = data.get("timeout_multiplier")

        task = data.get("task") or {}
        # Batch-level uses "tasks" list; task-level uses "task" dict
        tasks_list = data.get("tasks") or []
        if not task and tasks_list and isinstance(tasks_list, list):
            task = tasks_list[0]
        result["task_source"] = task.get("git_url") or task.get("path")

    # --- Extract from claude-code.txt init line ---
    if transcript_path is not None:
        tp = Path(transcript_path)
        if tp.is_file():
            try:
                for line in tp.open():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("type") == "system" and entry.get("subtype") == "init":
                        result["claude_code_version"] = entry.get("claude_code_version")
                        result["permission_mode"] = entry.get("permissionMode")
                        result["tools"] = entry.get("tools")
                        result["mcp_servers"] = entry.get("mcp_servers")
                        result["model"] = entry.get("model")
                        # Infer mcp_mode from mcp_servers + available tools
                        servers = entry.get("mcp_servers") or []
                        server_names = [s.get("name") for s in servers if isinstance(s, dict)]
                        tools_list = entry.get("tools") or []
                        has_sg = "sourcegraph" in server_names
                        has_ds_server = "deepsearch" in server_names
                        has_ds_tool = (
                            "mcp__sourcegraph__sg_deepsearch" in tools_list
                            or "mcp__deepsearch__deepsearch" in tools_list
                        )
                        if not server_names:
                            result["mcp_mode"] = "none"
                        elif has_sg and (has_ds_server or has_ds_tool):
                            result["mcp_mode"] = "sourcegraph_full"
                        elif has_sg:
                            result["mcp_mode"] = "sourcegraph_base"
                        elif has_ds_server or has_ds_tool:
                            result["mcp_mode"] = "deepsearch"
                        else:
                            result["mcp_mode"] = ",".join(server_names)
                        break
            except OSError:
                pass

    return result


def _empty_search_patterns() -> dict:
    """Return a dict with all search pattern fields set to None."""
    return {
        "search_queries": None,
        "search_calls_keyword": None,
        "search_calls_nls": None,
        "search_calls_deepsearch": None,
        "deepsearch_keyword_ratio": None,
    }


# MCP search tool name mappings
_SEARCH_TOOL_MAP = {
    "mcp__sourcegraph__sg_keyword_search": "keyword",
    "mcp__sourcegraph__sg_nls_search": "nls",
    "mcp__sourcegraph__sg_deepsearch": "deepsearch",
    # Also support short names without server prefix
    "sg_keyword_search": "keyword",
    "sg_nls_search": "nls",
    "sg_deepsearch": "deepsearch",
}


def _classify_search_tool(name: str) -> Optional[str]:
    """Classify a tool name as keyword/nls/deepsearch, or None."""
    if name in _SEARCH_TOOL_MAP:
        return _SEARCH_TOOL_MAP[name]
    # Handle variations like mcp__<server>__sg_keyword_search
    for suffix, category in (
        ("sg_keyword_search", "keyword"),
        ("sg_nls_search", "nls"),
        ("sg_deepsearch", "deepsearch"),
    ):
        if name.endswith(suffix):
            return category
    return None


def _build_search_results(
    queries: list[dict],
    counts: dict[str, int],
) -> dict:
    """Build the standard search pattern dict from collected data."""
    keyword = counts.get("keyword", 0)
    nls = counts.get("nls", 0)
    deepsearch = counts.get("deepsearch", 0)
    total_search = keyword + nls + deepsearch

    if total_search == 0:
        return _empty_search_patterns()

    ds_ratio = deepsearch / total_search if total_search > 0 else None

    return {
        "search_queries": queries if queries else None,
        "search_calls_keyword": keyword,
        "search_calls_nls": nls,
        "search_calls_deepsearch": deepsearch,
        "deepsearch_keyword_ratio": ds_ratio,
    }


def extract_search_patterns_from_trajectory(
    trajectory_json_path: str | Path,
) -> dict:
    """Parse ATIF v1.2 trajectory.json to extract MCP search tool usage.

    Iterates steps[].tool_calls[] looking for function_names matching
    MCP search tools (sg_keyword_search, sg_nls_search, sg_deepsearch).

    Args:
        trajectory_json_path: Path to the agent/trajectory.json file.

    Returns:
        Dict with keys: search_queries, search_calls_keyword,
        search_calls_nls, search_calls_deepsearch, deepsearch_keyword_ratio.
    """
    path = Path(trajectory_json_path)
    if not path.is_file():
        return _empty_search_patterns()

    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return _empty_search_patterns()

    queries: list[dict] = []
    counts: dict[str, int] = {}

    steps = data.get("steps") or []
    for step_idx, step in enumerate(steps):
        step_id = step.get("step_id", step_idx)
        tool_calls = step.get("tool_calls") or []
        for tc in tool_calls:
            name = tc.get("function_name") or ""
            category = _classify_search_tool(name)
            if category is None:
                continue
            counts[category] = counts.get(category, 0) + 1
            args = tc.get("arguments") or {}
            query = args.get("query", "")
            queries.append({
                "tool": name,
                "query": query,
                "step_id": step_id,
            })

    return _build_search_results(queries, counts)


def extract_search_patterns_from_transcript(
    claude_code_txt_path: str | Path,
) -> dict:
    """Parse claude-code.txt JSONL to extract MCP search tool usage.

    Fallback when trajectory.json is missing.

    Args:
        claude_code_txt_path: Path to the agent/claude-code.txt JSONL file.

    Returns:
        Dict with same schema as extract_search_patterns_from_trajectory.
    """
    path = Path(claude_code_txt_path)
    if not path.is_file():
        return _empty_search_patterns()

    try:
        lines = path.read_text().splitlines()
    except OSError:
        return _empty_search_patterns()

    queries: list[dict] = []
    counts: dict[str, int] = {}
    step_counter = 0

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
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name") or ""
            category = _classify_search_tool(name)
            if category is None:
                continue
            counts[category] = counts.get(category, 0) + 1
            inp = block.get("input") or {}
            query = inp.get("query", "")
            queries.append({
                "tool": name,
                "query": query,
                "step_id": step_counter,
            })
        step_counter += 1

    return _build_search_results(queries, counts)


def _empty_code_changes() -> dict:
    """Return a dict with all code change fields set to None."""
    return {
        "files_modified": None,
        "lines_added": None,
        "lines_removed": None,
    }


def extract_code_changes_from_trajectory(
    trajectory_json_path: str | Path,
) -> dict:
    """Parse trajectory.json to extract code change metrics.

    Looks for Edit and Write tool calls to count files modified,
    lines added, and lines removed.

    Args:
        trajectory_json_path: Path to the agent/trajectory.json file.

    Returns:
        Dict with keys: files_modified, lines_added, lines_removed.
    """
    path = Path(trajectory_json_path)
    if not path.is_file():
        return _empty_code_changes()

    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return _empty_code_changes()

    files_touched: set[str] = set()
    lines_added = 0
    lines_removed = 0

    steps = data.get("steps") or []
    for step in steps:
        tool_calls = step.get("tool_calls") or []
        for tc in tool_calls:
            name = tc.get("function_name") or ""
            args = tc.get("arguments") or {}

            if name == "Edit":
                fp = args.get("file_path")
                if fp:
                    files_touched.add(fp)
                old = args.get("old_string", "")
                new = args.get("new_string", "")
                if old:
                    lines_removed += old.count("\n") + 1
                if new:
                    lines_added += new.count("\n") + 1

            elif name == "Write":
                fp = args.get("file_path")
                if fp:
                    files_touched.add(fp)
                content = args.get("content", "")
                if content:
                    lines_added += content.count("\n") + 1

    if not files_touched:
        return _empty_code_changes()

    return {
        "files_modified": len(files_touched),
        "lines_added": lines_added,
        "lines_removed": lines_removed,
    }


def extract_code_changes_from_transcript(
    claude_code_txt_path: str | Path,
) -> dict:
    """Parse claude-code.txt JSONL to extract code change metrics.

    Fallback when trajectory.json is missing.

    Args:
        claude_code_txt_path: Path to the agent/claude-code.txt JSONL file.

    Returns:
        Dict with same schema as extract_code_changes_from_trajectory.
    """
    path = Path(claude_code_txt_path)
    if not path.is_file():
        return _empty_code_changes()

    try:
        lines = path.read_text().splitlines()
    except OSError:
        return _empty_code_changes()

    files_touched: set[str] = set()
    lines_added = 0
    lines_removed = 0

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
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name") or ""
            inp = block.get("input") or {}

            if name == "Edit":
                fp = inp.get("file_path")
                if fp:
                    files_touched.add(fp)
                old = inp.get("old_string", "")
                new = inp.get("new_string", "")
                if old:
                    lines_removed += old.count("\n") + 1
                if new:
                    lines_added += new.count("\n") + 1

            elif name == "Write":
                fp = inp.get("file_path")
                if fp:
                    files_touched.add(fp)
                content_str = inp.get("content", "")
                if content_str:
                    lines_added += content_str.count("\n") + 1

    if not files_touched:
        return _empty_code_changes()

    return {
        "files_modified": len(files_touched),
        "lines_added": lines_added,
        "lines_removed": lines_removed,
    }


# Opus 4.5 pricing (USD per million tokens)
_OPUS_INPUT_PRICE = 15.0
_OPUS_OUTPUT_PRICE = 75.0
_OPUS_CACHE_WRITE_PRICE = 18.75
_OPUS_CACHE_READ_PRICE = 1.50


def calculate_cost_from_tokens(
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    cache_creation: Optional[int] = None,
    cache_read: Optional[int] = None,
) -> Optional[float]:
    """Calculate USD cost from token counts using Opus 4.5 pricing.

    Args:
        input_tokens: Number of input tokens (non-cache).
        output_tokens: Number of output tokens.
        cache_creation: Number of cache creation (write) tokens.
        cache_read: Number of cache read tokens.

    Returns:
        Estimated cost in USD, or None if input/output tokens unavailable.
    """
    if input_tokens is None or output_tokens is None:
        return None

    cost = (input_tokens / 1_000_000) * _OPUS_INPUT_PRICE
    cost += (output_tokens / 1_000_000) * _OPUS_OUTPUT_PRICE
    if cache_creation:
        cost += (cache_creation / 1_000_000) * _OPUS_CACHE_WRITE_PRICE
    if cache_read:
        cost += (cache_read / 1_000_000) * _OPUS_CACHE_READ_PRICE

    return round(cost, 6)


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
