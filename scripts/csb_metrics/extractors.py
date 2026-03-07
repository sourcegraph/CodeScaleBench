"""Extract metrics from Harbor result.json and related files.

All extractors handle missing/malformed files gracefully by returning None
for missing fields. Stdlib only — no external dependencies.
"""

from __future__ import annotations

import json
import logging
import re
import statistics as _statistics
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import TaskMetrics
from .transcript_paths import infer_task_dir_from_transcript_path, resolve_task_transcript_path

logger = logging.getLogger(__name__)
_WARNED_UNKNOWN_PRICING_MODELS: set[str] = set()


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp, returning None on failure."""
    if not ts:
        return None
    try:
        # Python 3.10 fromisoformat doesn't handle 'Z' suffix
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _seconds_between(start: Optional[str], end: Optional[str]) -> Optional[float]:
    """Return seconds between two ISO timestamps, or None."""
    s = _parse_iso(start)
    e = _parse_iso(end)
    if s is None or e is None:
        return None
    return (e - s).total_seconds()


def _resolve_existing_transcript_path(transcript_path: str | Path) -> Path:
    """Resolve transcript path with task-level fallback candidates."""
    path = Path(transcript_path)
    if path.is_file():
        return path

    task_dir = infer_task_dir_from_transcript_path(path)
    if task_dir is not None:
        candidate = resolve_task_transcript_path(task_dir)
        if candidate.is_file():
            return candidate
    return path


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
    for key in ("reward", "score"):
        if key in rewards:
            try:
                reward = float(rewards[key])
            except (TypeError, ValueError):
                continue
            break

    # Status — agent timeouts are scored normally (verifier runs on partial work)
    exc = data.get("exception_info") or {}
    exc_type = exc.get("exception_type", exc.get("type", "")) if isinstance(exc, dict) else ""
    timed_out = bool(exc and exc_type == "AgentTimeoutError")
    if exc and not timed_out:
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
        timed_out=timed_out,
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
    path = _resolve_existing_transcript_path(claude_code_txt_path)
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


def extract_task_tokens_from_trajectory(
    trajectory_json_path: str | Path,
) -> dict:
    """Extract token usage from trajectory.json final_metrics.

    OpenHands trajectories include a ``final_metrics`` block with totals.
    Also sums per-step ``metrics`` if ``final_metrics`` is absent.
    """
    empty = {
        "input_tokens": None,
        "output_tokens": None,
        "cache_creation_input_tokens": None,
        "cache_read_input_tokens": None,
        "total_cost_usd": None,
    }
    path = Path(trajectory_json_path)
    if not path.is_file():
        return empty
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return empty

    fm = data.get("final_metrics") or {}
    if fm.get("total_prompt_tokens") is not None:
        return {
            "input_tokens": fm.get("total_prompt_tokens"),
            "output_tokens": fm.get("total_completion_tokens"),
            "cache_creation_input_tokens": None,
            "cache_read_input_tokens": fm.get("total_cached_tokens"),
            "total_cost_usd": fm.get("total_cost_usd"),
        }

    # Fallback: sum per-step metrics
    prompt = comp = cached = 0
    cost = 0.0
    found = False
    for step in data.get("steps") or []:
        m = step.get("metrics")
        if m:
            found = True
            prompt += m.get("prompt_tokens", 0)
            comp += m.get("completion_tokens", 0)
            cached += m.get("cached_tokens", 0)
            cost += m.get("cost_usd", 0.0)
    if not found:
        return empty
    return {
        "input_tokens": prompt,
        "output_tokens": comp,
        "cache_creation_input_tokens": None,
        "cache_read_input_tokens": cached,
        "total_cost_usd": cost,
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
    # Claude Code tools
    "Bash", "Read", "Edit", "Write", "Grep", "Glob",
    "Task", "TaskOutput", "TodoWrite", "WebFetch", "WebSearch",
    "NotebookEdit", "AskUserQuestion", "EnterPlanMode", "ExitPlanMode",
    "Skill", "TaskStop", "ToolSearch",
    # OpenHands tools
    "execute_bash", "str_replace_editor", "read_file", "think", "finish",
    "task_tracker",
}


_OPENHANDS_MCP_TOOLS = {
    "keyword_search", "nls_search", "deepsearch", "list_repos",
    "read_file_content", "search_symbols", "get_file_metadata",
}


def _is_mcp_tool(name: str) -> bool:
    """Return True if the tool name indicates an MCP tool."""
    return name.startswith("mcp__") or name in _OPENHANDS_MCP_TOOLS


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
    path = _resolve_existing_transcript_path(claude_code_txt_path)
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
        tp = _resolve_existing_transcript_path(transcript_path)
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
                            result["mcp_mode"] = "sourcegraph_full"
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
    # OpenHands MCP tools (bare names, no mcp__ prefix)
    "keyword_search": "keyword",
    "nls_search": "nls",
    "deepsearch": "deepsearch",
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


def classify_search_strategy(
    keyword: int,
    nls: int,
    deepsearch: int,
) -> Optional[str]:
    """Classify search strategy from call counts.

    Returns:
        'keyword_only', 'nls_focused', 'deepsearch_heavy', 'mixed', or None.
    """
    total = keyword + nls + deepsearch
    if total == 0:
        return None
    if deepsearch > 0 and deepsearch >= keyword + nls:
        return "deepsearch_heavy"
    if nls > 0 and nls >= keyword:
        return "nls_focused"
    if keyword > 0 and nls == 0 and deepsearch == 0:
        return "keyword_only"
    return "mixed"


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
    path = _resolve_existing_transcript_path(claude_code_txt_path)
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

            elif name == "str_replace_editor":
                # OpenHands edit tool — commands: str_replace, create, insert
                fp = args.get("path")
                cmd = args.get("command", "")
                if fp:
                    files_touched.add(fp)
                if cmd == "str_replace":
                    old = args.get("old_str", "")
                    new = args.get("new_str", "")
                    if old:
                        lines_removed += old.count("\n") + 1
                    if new:
                        lines_added += new.count("\n") + 1
                elif cmd == "create":
                    text = args.get("file_text", "")
                    if text:
                        lines_added += text.count("\n") + 1
                elif cmd == "insert":
                    text = args.get("new_str", "")
                    if text:
                        lines_added += text.count("\n") + 1

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
    path = _resolve_existing_transcript_path(claude_code_txt_path)
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


# Model pricing registry (USD per million tokens)
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Claude 4.x family
    "claude-opus-4-5-20250514":   {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
    "claude-opus-4-6":            {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
    "claude-sonnet-4-5-20250929": {"input": 3.0,  "output": 15.0, "cache_write": 3.75,  "cache_read": 0.30},
    "claude-haiku-4-5-20251001":  {"input": 0.80, "output": 4.0,  "cache_write": 1.0,   "cache_read": 0.08},
    # GPT family
    "gpt-4o":      {"input": 2.50, "output": 10.0, "cache_write": 0, "cache_read": 0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cache_write": 0, "cache_read": 0},
    "gpt-5.3-codex": {"input": 1.50, "output": 6.0, "cache_write": 0, "cache_read": 0},
    "o1":          {"input": 15.0, "output": 60.0, "cache_write": 0, "cache_read": 0},
    # Gemini family
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40, "cache_write": 0, "cache_read": 0},
    "gemini-1.5-pro":   {"input": 1.25, "output": 5.0,  "cache_write": 0, "cache_read": 0},
}
_DEFAULT_MODEL = "claude-opus-4-5-20250514"


def calculate_cost_from_tokens(
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    cache_creation: Optional[int] = None,
    cache_read: Optional[int] = None,
    model: str = _DEFAULT_MODEL,
) -> Optional[float]:
    """Calculate USD cost from token counts.

    Args:
        input_tokens: Number of input tokens (non-cache).
        output_tokens: Number of output tokens.
        cache_creation: Number of cache creation (write) tokens.
        cache_read: Number of cache read tokens.
        model: Model identifier (key into MODEL_PRICING). Unknown models
            deterministically fall back to default Opus 4.5 pricing and emit
            a one-time warning per model.

    Returns:
        Estimated cost in USD, or None if input/output tokens unavailable.
    """
    if input_tokens is None or output_tokens is None:
        return None

    prices = MODEL_PRICING.get(model)
    if prices is None:
        prices = MODEL_PRICING[_DEFAULT_MODEL]
        if model not in _WARNED_UNKNOWN_PRICING_MODELS:
            logger.warning(
                "Unknown model pricing for '%s'; using fallback '%s' rates",
                model,
                _DEFAULT_MODEL,
            )
            _WARNED_UNKNOWN_PRICING_MODELS.add(model)

    cost = (input_tokens / 1_000_000) * prices["input"]
    cost += (output_tokens / 1_000_000) * prices["output"]
    if cache_creation:
        cost += (cache_creation / 1_000_000) * prices["cache_write"]
    if cache_read:
        cost += (cache_read / 1_000_000) * prices["cache_read"]

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


# ---------------------------------------------------------------------------
# Tier 1 extractors
# ---------------------------------------------------------------------------


def extract_error_fingerprint(
    result_json_path: str | Path,
) -> Optional[dict]:
    """Classify exception_info from result.json using status_fingerprints.

    Lazy-imports fingerprint_error to avoid circular deps.

    Returns:
        Dict with fingerprint_id, label, severity (subset), or None.
    """
    path = Path(result_json_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    exception_info = data.get("exception_info")
    if not exception_info:
        return None

    try:
        from status_fingerprints import fingerprint_error
    except ImportError:
        import sys
        # Ensure scripts/ is on sys.path
        scripts_dir = str(Path(__file__).resolve().parent.parent)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from status_fingerprints import fingerprint_error

    result = fingerprint_error(exception_info)
    if result is None:
        return None
    # Return a compact subset for the metrics file
    return {
        "fingerprint_id": result.get("fingerprint_id"),
        "label": result.get("label"),
        "severity": result.get("severity"),
    }


def extract_verifier_test_summary(
    test_stdout_path: str | Path,
    benchmark: str = "",
) -> Optional[dict]:
    """Parse verifier/test-stdout.txt with benchmark-specific logic.

    Returns:
        Dict with tests_passed, tests_total, failure_reasons, raw_score.
        None if file missing or unparseable.
    """
    path = Path(test_stdout_path)
    if not path.is_file():
        return None
    try:
        text = path.read_text()
    except OSError:
        return None

    bench_lower = benchmark.lower()

    # SWE-bench: "Required tests: N" / "Required tests that passed: M"
    if "swebench" in bench_lower:
        req = re.search(r"Required tests:\s*(\d+)", text)
        passed = re.search(r"Required tests that passed:\s*(\d+)", text)
        if req and passed:
            total = int(req.group(1))
            p = int(passed.group(1))
            return {
                "tests_passed": p,
                "tests_total": total,
                "failure_reasons": [],
                "raw_score": p / total if total > 0 else 0.0,
            }

    # LoCoBench: "Score: X.XXXX"
    if "locobench" in bench_lower:
        m = re.search(r"Score:\s*([0-9.]+)", text)
        if m:
            score = float(m.group(1))
            return {
                "tests_passed": None,
                "tests_total": None,
                "failure_reasons": [],
                "raw_score": score,
            }

    # PyTorch: count [PASS] / [FAIL] lines
    if "pytorch" in bench_lower:
        passes = len(re.findall(r"\[PASS\]", text))
        fails = len(re.findall(r"\[FAIL\]", text))
        total = passes + fails
        if total > 0:
            fail_lines = [
                line.strip() for line in text.splitlines()
                if "[FAIL]" in line
            ]
            return {
                "tests_passed": passes,
                "tests_total": total,
                "failure_reasons": fail_lines[:10],
                "raw_score": passes / total,
            }

    # Generic fallback: count PASS/FAIL patterns
    passes = len(re.findall(r"\bPASS(?:ED)?\b", text, re.IGNORECASE))
    fails = len(re.findall(r"\bFAIL(?:ED)?\b", text, re.IGNORECASE))
    total = passes + fails
    if total > 0:
        fail_lines = [
            line.strip() for line in text.splitlines()
            if re.search(r"\bFAIL(?:ED)?\b", line, re.IGNORECASE)
        ]
        return {
            "tests_passed": passes,
            "tests_total": total,
            "failure_reasons": fail_lines[:10],
            "raw_score": passes / total,
        }

    return None


def extract_agent_return_code(
    task_dir: str | Path,
) -> Optional[int]:
    """Read agent/command-1/return-code.txt and return the integer."""
    path = Path(task_dir) / "agent" / "command-1" / "return-code.txt"
    if not path.is_file():
        return None
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def extract_mcp_info(
    task_dir: str | Path,
) -> dict:
    """Read agent/.mcp.json for MCP config presence and server names.

    Returns:
        Dict with mcp_config_present (bool) and mcp_servers (list[str]|None).
    """
    path = Path(task_dir) / "agent" / ".mcp.json"
    if not path.is_file():
        return {"mcp_config_present": False, "mcp_servers": None}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"mcp_config_present": True, "mcp_servers": None}

    servers = data.get("mcpServers") or {}
    return {
        "mcp_config_present": True,
        "mcp_servers": sorted(servers.keys()) if servers else None,
    }


def extract_instruction_length(
    task_dir: str | Path,
) -> Optional[int]:
    """Return character count of agent/instruction.txt."""
    path = Path(task_dir) / "agent" / "instruction.txt"
    if not path.is_file():
        return None
    try:
        return len(path.read_text())
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Tier 2 extractors
# ---------------------------------------------------------------------------

# Context window size for Opus (tokens)
_CONTEXT_WINDOW = 200_000


def extract_conversation_analysis_from_transcript(
    claude_code_txt_path: str | Path,
) -> dict:
    """Single-pass JSONL scan for conversation metrics.

    Returns dict with: conversation_turns, tool_errors_total,
    tool_errors_by_name, backtrack_count, context_window_peak_pct.
    All values None if file missing.
    """
    empty = {
        "conversation_turns": None,
        "tool_errors_total": None,
        "tool_errors_by_name": None,
        "backtrack_count": None,
        "context_window_peak_pct": None,
    }
    path = _resolve_existing_transcript_path(claude_code_txt_path)
    if not path.is_file():
        return empty

    try:
        lines = path.read_text().splitlines()
    except OSError:
        return empty

    assistant_turns = 0
    # Map tool_use id -> tool name (from assistant entries)
    pending_tool_uses: dict[str, str] = {}
    tool_errors_total = 0
    tool_errors_by_name: dict[str, int] = {}
    # Track files edited for backtrack counting
    edited_files: set[str] = set()
    backtrack_count = 0
    peak_input = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = entry.get("type")

        if etype == "assistant":
            assistant_turns += 1
            message = entry.get("message") or {}
            content = message.get("content") or []
            # Track usage for context window peak
            usage = message.get("usage") or entry.get("usage") or {}
            inp = (usage.get("input_tokens") or 0)
            cache_create = (usage.get("cache_creation_input_tokens") or 0)
            cache_read = (usage.get("cache_read_input_tokens") or 0)
            total_input = inp + cache_create + cache_read
            if total_input > peak_input:
                peak_input = total_input

            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    tool_id = block.get("id")
                    tool_name = block.get("name", "")
                    if tool_id:
                        pending_tool_uses[tool_id] = tool_name
                    # Backtrack: Edit to already-edited file
                    if tool_name == "Edit":
                        fp = (block.get("input") or {}).get("file_path")
                        if fp:
                            if fp in edited_files:
                                backtrack_count += 1
                            edited_files.add(fp)

        elif etype == "tool_result":
            # Check for is_error on tool results
            content_blocks = entry.get("content") or []
            tool_use_id = entry.get("tool_use_id")
            is_error = entry.get("is_error", False)
            # Also check content-level is_error
            if not is_error and isinstance(content_blocks, list):
                for cb in content_blocks:
                    if isinstance(cb, dict) and cb.get("is_error"):
                        is_error = True
                        break
            if is_error:
                tool_errors_total += 1
                name = pending_tool_uses.get(tool_use_id, "unknown")
                tool_errors_by_name[name] = tool_errors_by_name.get(name, 0) + 1

    if assistant_turns == 0:
        return empty

    ctx_peak = (peak_input / _CONTEXT_WINDOW) if peak_input > 0 else None

    return {
        "conversation_turns": assistant_turns,
        "tool_errors_total": tool_errors_total,
        "tool_errors_by_name": tool_errors_by_name if tool_errors_by_name else None,
        "backtrack_count": backtrack_count,
        "context_window_peak_pct": round(ctx_peak, 4) if ctx_peak is not None else None,
    }


def extract_conversation_analysis_from_trajectory(
    trajectory_json_path: str | Path,
) -> dict:
    """Extract conversation metrics from ATIF trajectory.json.

    Returns same schema as transcript version (minus context_window_peak_pct
    which is transcript-only).
    """
    empty = {
        "conversation_turns": None,
        "tool_errors_total": None,
        "tool_errors_by_name": None,
        "backtrack_count": None,
        "context_window_peak_pct": None,
    }
    path = Path(trajectory_json_path)
    if not path.is_file():
        return empty

    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return empty

    steps = data.get("steps") or []
    if not steps:
        return empty

    assistant_turns = 0
    tool_errors_total = 0
    tool_errors_by_name: dict[str, int] = {}
    edited_files: set[str] = set()
    backtrack_count = 0

    for step in steps:
        # Each step with tool_calls or output counts as an assistant turn
        if step.get("tool_calls") or step.get("output"):
            assistant_turns += 1

        tool_calls = step.get("tool_calls") or []
        tool_results = step.get("tool_results") or []

        # Build a map of tool call index -> name for error attribution
        tc_names = {}
        for i, tc in enumerate(tool_calls):
            name = tc.get("function_name") or ""
            tc_names[i] = name
            # Backtrack
            if name == "Edit":
                fp = (tc.get("arguments") or {}).get("file_path")
                if fp:
                    if fp in edited_files:
                        backtrack_count += 1
                    edited_files.add(fp)

        # Check tool results for errors
        for i, tr in enumerate(tool_results):
            is_error = tr.get("is_error", False)
            if is_error:
                tool_errors_total += 1
                name = tc_names.get(i, "unknown")
                tool_errors_by_name[name] = tool_errors_by_name.get(name, 0) + 1

    if assistant_turns == 0:
        return empty

    return {
        "conversation_turns": assistant_turns,
        "tool_errors_total": tool_errors_total,
        "tool_errors_by_name": tool_errors_by_name if tool_errors_by_name else None,
        "backtrack_count": backtrack_count,
        "context_window_peak_pct": None,  # Not available from trajectory
    }


def extract_mcp_latency_from_trajectory(
    trajectory_json_path: str | Path,
) -> dict:
    """Compute MCP call latency from trajectory step timestamps.

    Duration = next_step.timestamp - current_step.timestamp for MCP calls.
    This is an approximation that includes model inference overhead.

    Returns:
        Dict with mcp_latency_p50_ms and mcp_latency_p95_ms, or None values.
    """
    empty = {"mcp_latency_p50_ms": None, "mcp_latency_p95_ms": None}
    path = Path(trajectory_json_path)
    if not path.is_file():
        return empty

    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return empty

    steps = data.get("steps") or []
    if len(steps) < 2:
        return empty

    # Collect (step_index, timestamp) for steps with MCP tool calls
    mcp_step_indices: list[int] = []
    timestamps: list[Optional[datetime]] = []

    for i, step in enumerate(steps):
        ts = _parse_iso(step.get("timestamp"))
        timestamps.append(ts)
        tool_calls = step.get("tool_calls") or []
        for tc in tool_calls:
            name = tc.get("function_name") or ""
            if _is_mcp_tool(name):
                mcp_step_indices.append(i)
                break  # Only count step once

    if not mcp_step_indices:
        return empty

    # Compute durations: time from MCP step to next step
    durations_ms: list[float] = []
    for idx in mcp_step_indices:
        if idx + 1 < len(timestamps):
            t_start = timestamps[idx]
            t_end = timestamps[idx + 1]
            if t_start is not None and t_end is not None:
                delta_ms = (t_end - t_start).total_seconds() * 1000
                if delta_ms >= 0:
                    durations_ms.append(delta_ms)

    if not durations_ms:
        return empty

    p50 = _statistics.median(durations_ms)
    if len(durations_ms) >= 2:
        try:
            p95 = _statistics.quantiles(durations_ms, n=20)[-1]  # 95th percentile
        except _statistics.StatisticsError:
            p95 = max(durations_ms)
    else:
        p95 = durations_ms[0]

    return {
        "mcp_latency_p50_ms": round(p50, 1),
        "mcp_latency_p95_ms": round(p95, 1),
    }


def extract_compaction_events_from_transcript(
    claude_code_txt_path: str | Path,
) -> dict:
    """Extract context compaction events from a claude-code.txt transcript.

    Compaction appears as a three-event sequence in the JSONL:
      1. {"type": "system", "subtype": "status", "status": "compacting"}
      2. {"type": "system", "subtype": "status", "status": null}
      3. {"type": "system", "subtype": "compact_boundary",
          "compact_metadata": {"trigger": "auto", "pre_tokens": N}}

    Also detects the token drop by tracking input_tokens on assistant turns
    before and after each compact_boundary event.

    Returns:
        Dict with:
          compaction_count: int — number of compaction events
          compaction_events: list[dict] — per-event details:
            - turn_index: assistant turn number when compaction occurred
            - pre_tokens: token count that triggered compaction (from metadata)
            - post_tokens: first assistant turn input_tokens after compaction
            - tokens_dropped: pre_tokens - post_tokens
            - trigger: "auto" or other (from metadata)
          compaction_first_turn_pct: float — first compaction turn / total turns
          compaction_total_tokens_dropped: int — sum of all tokens_dropped
        All None if no transcript or no compaction events.
    """
    empty: dict = {
        "compaction_count": 0,
        "compaction_events": None,
        "compaction_first_turn_pct": None,
        "compaction_total_tokens_dropped": None,
    }
    path = _resolve_existing_transcript_path(claude_code_txt_path)
    if not path.is_file():
        return empty

    try:
        lines = path.read_text().splitlines()
    except OSError:
        return empty

    assistant_turn_count = 0
    pending_compact: dict | None = None
    events: list[dict] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        etype = entry.get("type")

        if etype == "assistant":
            assistant_turn_count += 1
            message = entry.get("message") or {}
            usage = message.get("usage") or entry.get("usage") or {}
            inp = usage.get("input_tokens") or 0
            cache_create = usage.get("cache_creation_input_tokens") or 0
            cache_read = usage.get("cache_read_input_tokens") or 0
            total_input = inp + cache_create + cache_read

            if pending_compact is not None and total_input > 0:
                pending_compact["post_tokens"] = total_input
                pre = pending_compact.get("pre_tokens") or 0
                pending_compact["tokens_dropped"] = pre - total_input
                events.append(pending_compact)
                pending_compact = None

        elif etype == "system":
            subtype = entry.get("subtype")
            if subtype == "compact_boundary":
                metadata = entry.get("compact_metadata") or {}
                pending_compact = {
                    "turn_index": assistant_turn_count,
                    "pre_tokens": metadata.get("pre_tokens"),
                    "post_tokens": None,
                    "tokens_dropped": None,
                    "trigger": metadata.get("trigger", "unknown"),
                }

    if pending_compact is not None:
        events.append(pending_compact)

    if not events:
        return empty

    total_dropped = sum(
        e["tokens_dropped"] for e in events if e["tokens_dropped"] is not None
    )
    first_turn_pct = (
        round(events[0]["turn_index"] / assistant_turn_count, 4)
        if assistant_turn_count > 0
        else None
    )

    return {
        "compaction_count": len(events),
        "compaction_events": events,
        "compaction_first_turn_pct": first_turn_pct,
        "compaction_total_tokens_dropped": total_dropped if total_dropped else None,
    }
