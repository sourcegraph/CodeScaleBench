"""MCP retrieval metrics extractor — baseline and MCP compatible.

Parses agent transcripts (trajectory.json or claude-code.txt) to measure
oracle item coverage and context retrieval efficiency.

Oracle items are {repo, path, symbol?} dicts from task_spec.json
artifacts.oracle (required_files, required_symbols, dependency_chains).

Oracle coverage counts items found via ANY tool (local or MCP) — this
enables fair comparison: baseline CAN score non-zero if it finds oracle
items in locally checked-out repos.

Stdlib only.  python3 -m py_compile succeeds.

Usage
-----
As a library::

    from ccb_metrics.retrieval import extract_retrieval_metrics, load_oracle_items
    items = load_oracle_items("tests/task_spec.json")
    metrics = extract_retrieval_metrics("runs/staging/.../task__hash", items)

As a CLI::

    python3 retrieval.py --task-dir <harbor_output_dir> \\
        --task-spec <path_to_task_spec.json> \\
        [--output retrieval_metrics.json] [--verbose]
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Oracle item loading
# ---------------------------------------------------------------------------

def load_oracle_items(task_spec_path: str | Path) -> list[dict]:
    """Load oracle items from a task_spec.json file.

    Returns a list of dicts, each with at minimum ``type`` (``'file'`` or
    ``'symbol'``), ``repo``, and ``path``.  Symbol items also have
    ``symbol``.  Items derived from dependency_chain steps are tagged
    ``type='file'``.

    Args:
        task_spec_path: Path to the task_spec.json file.

    Returns:
        List of oracle item dicts.  Empty list if file missing or malformed.

    >>> load_oracle_items("/nonexistent/task_spec.json")
    []
    """
    path = Path(task_spec_path)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []

    oracle = (data.get("artifacts") or {}).get("oracle") or {}
    items: list[dict] = []

    for f in oracle.get("required_files") or []:
        repo = f.get("repo", "")
        file_path = f.get("path", "")
        if repo and file_path:
            items.append({"type": "file", "repo": repo, "path": file_path})

    for s in oracle.get("required_symbols") or []:
        repo = s.get("repo", "")
        file_path = s.get("path", "")
        symbol = s.get("symbol", "")
        if repo:
            items.append({
                "type": "symbol",
                "repo": repo,
                "path": file_path,
                "symbol": symbol,
            })

    # Dependency-chain steps as file items (deduplicated)
    seen_files: set[tuple[str, str]] = {
        (i["repo"], i["path"]) for i in items if i["type"] == "file"
    }
    for chain in oracle.get("dependency_chains") or []:
        for step in chain.get("steps") or []:
            repo = step.get("repo", "")
            file_path = step.get("path", "")
            if repo and file_path and (repo, file_path) not in seen_files:
                seen_files.add((repo, file_path))
                items.append({"type": "file", "repo": repo, "path": file_path})

    return items


# ---------------------------------------------------------------------------
# Path / repo matching helpers
# ---------------------------------------------------------------------------

def _extract_org_from_repo(repo: str) -> str:
    """Return the org portion of an ``org/repo`` string.

    >>> _extract_org_from_repo("kubernetes/kubernetes")
    'kubernetes'
    >>> _extract_org_from_repo("sg-benchmarks/kubernetes-client-go")
    'sg-benchmarks'
    >>> _extract_org_from_repo("standalone")
    'standalone'
    """
    parts = repo.split("/")
    return parts[0] if parts else repo


def _path_matches(oracle_path: str, candidate_path: str) -> bool:
    """Return True if *candidate_path* refers to the same file as *oracle_path*.

    Handles exact matches and suffix matches so that absolute container
    paths (``/workspace/dynamic/scheme.go``) match oracle relative paths
    (``dynamic/scheme.go``).

    >>> _path_matches("dynamic/client_test.go", "dynamic/client_test.go")
    True
    >>> _path_matches("dynamic/client_test.go", "/workspace/dynamic/client_test.go")
    True
    >>> _path_matches("dynamic/client_test.go", "/workspace/other/dynamic/other.go")
    False
    >>> _path_matches("", "/any/path")
    False
    """
    if not oracle_path:
        return False
    if oracle_path == candidate_path:
        return True
    oracle_norm = oracle_path.lstrip("/")
    candidate_norm = candidate_path.lstrip("/")
    return (
        candidate_norm == oracle_norm
        or candidate_norm.endswith("/" + oracle_norm)
    )


# ---------------------------------------------------------------------------
# Oracle-hit detection per tool call
# ---------------------------------------------------------------------------

def _tool_base_name(tool_name: str) -> str:
    """Strip the ``mcp__<server>__`` prefix from an MCP tool name.

    >>> _tool_base_name("mcp__sourcegraph__read_file")
    'read_file'
    >>> _tool_base_name("mcp__sg__keyword_search")
    'keyword_search'
    >>> _tool_base_name("Read")
    'Read'
    """
    if tool_name.startswith("mcp__") and "__" in tool_name[5:]:
        return tool_name.rsplit("__", 1)[-1]
    return tool_name


def _check_mcp_tool_hit(tool_name: str, args: dict, oracle_item: dict) -> bool:
    """Return True if an MCP tool call directly accesses an oracle item.

    Detects hits for:

    - ``read_file``:  args ``repo`` + ``path`` match a file/symbol item
    - ``find_references`` / ``go_to_definition``:  match on repo/path/symbol

    Search tools (keyword_search, nls_search, deepsearch) are excluded
    because they do not guarantee the oracle file was actually read.

    >>> _check_mcp_tool_hit(
    ...     "mcp__sourcegraph__read_file",
    ...     {"repo": "sg-benchmarks/kubernetes-client-go", "path": "dynamic/scheme.go"},
    ...     {"type": "file", "repo": "sg-benchmarks/kubernetes-client-go", "path": "dynamic/scheme.go"})
    True
    >>> _check_mcp_tool_hit(
    ...     "mcp__sourcegraph__read_file",
    ...     {"repo": "sg-benchmarks/kubernetes-client-go", "path": "dynamic/other.go"},
    ...     {"type": "file", "repo": "sg-benchmarks/kubernetes-client-go", "path": "dynamic/scheme.go"})
    False
    """
    base = _tool_base_name(tool_name)

    if base == "read_file":
        arg_repo = args.get("repo", "")
        arg_path = args.get("path", "")
        return (
            arg_repo == oracle_item["repo"]
            and _path_matches(oracle_item["path"], arg_path)
        )

    if base in ("find_references", "go_to_definition"):
        arg_repo = args.get("repo", "")
        arg_path = args.get("path", "")
        arg_symbol = args.get("symbol", "")
        if oracle_item["type"] == "symbol":
            repo_ok = not arg_repo or arg_repo == oracle_item["repo"]
            path_ok = not arg_path or _path_matches(oracle_item.get("path", ""), arg_path)
            sym_ok = not arg_symbol or arg_symbol == oracle_item.get("symbol", "")
            return repo_ok and path_ok and sym_ok
        if oracle_item["type"] == "file":
            return (
                arg_repo == oracle_item["repo"]
                and _path_matches(oracle_item["path"], arg_path)
            )

    return False


def _check_local_tool_hit(tool_name: str, args: dict, oracle_item: dict) -> bool:
    """Return True if a local tool call directly accesses an oracle item.

    Detects hits for:

    - ``Read``:  ``file_path`` suffix-matches oracle ``path``
    - ``Grep`` / ``Glob``:  ``pattern`` contains oracle symbol name
    - ``Bash``:  ``command`` contains the oracle file path as substring

    Note: repo matching is omitted for local tools — the container path
    does not encode the repo, so we rely on path suffix matching.

    >>> _check_local_tool_hit(
    ...     "Read", {"file_path": "/workspace/dynamic/scheme.go"},
    ...     {"type": "file", "repo": "sg-benchmarks/kubernetes-client-go", "path": "dynamic/scheme.go"})
    True
    >>> _check_local_tool_hit(
    ...     "Read", {"file_path": "/workspace/other/file.go"},
    ...     {"type": "file", "repo": "sg-benchmarks/kubernetes-client-go", "path": "dynamic/scheme.go"})
    False
    """
    if tool_name == "Read":
        file_path = args.get("file_path", "")
        return _path_matches(oracle_item["path"], file_path)

    if tool_name in ("Grep", "Glob"):
        pattern = args.get("pattern", "")
        if oracle_item["type"] == "symbol":
            symbol = oracle_item.get("symbol", "")
            return bool(symbol and symbol in pattern)
        # Also check if glob pattern contains the oracle path
        return bool(pattern and _path_matches(oracle_item["path"], pattern))

    if tool_name == "Bash":
        cmd = args.get("command", "")
        oracle_path = oracle_item.get("path", "")
        return bool(oracle_path and oracle_path in cmd)

    return False


# ---------------------------------------------------------------------------
# Repo extraction from tool calls
# ---------------------------------------------------------------------------

_REPO_HOST_PREFIXES = ("github.com/", "gitlab.com/", "bitbucket.org/", "sourcegraph.com/")


def _normalize_repo(repo: str) -> str:
    """Strip common code-host prefixes from a repo identifier.

    Converts ``github.com/org/repo`` → ``org/repo``.

    >>> _normalize_repo("github.com/grafana/grafana")
    'grafana/grafana'
    >>> _normalize_repo("grafana/grafana")
    'grafana/grafana'
    >>> _normalize_repo("sg-benchmarks/kubernetes-client-go")
    'sg-benchmarks/kubernetes-client-go'
    """
    for prefix in _REPO_HOST_PREFIXES:
        if repo.startswith(prefix):
            return repo[len(prefix):]
    return repo


def _extract_repo_from_tool_call(tool_name: str, args: dict) -> Optional[str]:
    """Return the repo touched by this tool call, or None.

    Extracts from the ``repo`` arg for MCP tools that accept it, and
    parses ``repo:`` filter fragments from search query strings.
    The returned value is normalized (host prefix stripped).

    >>> _extract_repo_from_tool_call(
    ...     "mcp__sourcegraph__read_file",
    ...     {"repo": "grafana/grafana", "path": "pkg/api.go"})
    'grafana/grafana'
    >>> _extract_repo_from_tool_call("Read", {"file_path": "/workspace/pkg/api.go"}) is None
    True
    """
    if tool_name.startswith("mcp__"):
        repo = args.get("repo")
        if repo:
            return _normalize_repo(str(repo))
        # Try to extract repo from search query: repo:^org/name$ or repo:^github.com/org/name$
        query = args.get("query", "")
        if query:
            m = re.search(r"repo:(?:\^?)([A-Za-z0-9._/-]+?)(?:\$)?(?:\s|$)", query)
            if m:
                extracted = m.group(1).strip("^$")
                return _normalize_repo(extracted)
    return None


# ---------------------------------------------------------------------------
# Timestamp utilities
# ---------------------------------------------------------------------------

def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp string, returning None on failure."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Transcript / trajectory discovery
# ---------------------------------------------------------------------------

def _find_trajectory_path(task_dir: Path) -> Optional[Path]:
    """Return the trajectory.json path if it exists."""
    for rel in ("agent/trajectory.json", "trajectory.json"):
        p = task_dir / rel
        if p.is_file():
            return p
    return None


def _find_transcript_path(task_dir: Path) -> Optional[Path]:
    """Return the first JSONL transcript found under task_dir."""
    candidates = (
        "agent/claude-code.txt",
        "agent/transcript.jsonl",
        "claude-code.txt",
        "transcript.jsonl",
        "agent_output/claude-code.txt",
        "agent_output/transcript.jsonl",
    )
    for rel in candidates:
        p = task_dir / rel
        if p.is_file():
            return p
    return None


# ---------------------------------------------------------------------------
# Tool-call extraction from either source
# ---------------------------------------------------------------------------

# (tool_name, args_dict, timestamp_iso_or_None)
_ToolCall = tuple[str, dict, Optional[str]]


def _tool_calls_from_trajectory(data: dict) -> list[_ToolCall]:
    """Extract tool calls from trajectory.json data."""
    results: list[_ToolCall] = []
    for step in data.get("steps") or []:
        ts = step.get("timestamp")
        for tc in step.get("tool_calls") or []:
            name = tc.get("function_name") or ""
            args = tc.get("arguments") or {}
            if name:
                results.append((name, args, ts))
    return results


def _tool_calls_from_jsonl(lines: list[str]) -> list[_ToolCall]:
    """Extract tool calls from JSONL transcript lines."""
    results: list[_ToolCall] = []
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
        ts = entry.get("timestamp")
        message = entry.get("message") or {}
        for block in message.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name") or ""
            # JSONL uses "input"; trajectory uses "arguments"
            args = block.get("input") or block.get("arguments") or {}
            if name:
                results.append((name, args, ts))
    return results


def _load_tool_calls(task_dir: Path) -> list[_ToolCall]:
    """Load tool calls from trajectory.json, falling back to claude-code.txt."""
    traj = _find_trajectory_path(task_dir)
    if traj is not None:
        try:
            data = json.loads(traj.read_text())
            calls = _tool_calls_from_trajectory(data)
            if calls:
                return calls
        except (OSError, json.JSONDecodeError):
            pass

    transcript = _find_transcript_path(task_dir)
    if transcript is not None:
        try:
            lines = transcript.read_text().splitlines()
            return _tool_calls_from_jsonl(lines)
        except OSError:
            pass

    return []


# ---------------------------------------------------------------------------
# Local tool set
# ---------------------------------------------------------------------------

_LOCAL_TOOLS: frozenset[str] = frozenset({
    "Bash", "Read", "Edit", "Write", "Grep", "Glob",
    "Task", "TaskOutput", "TodoWrite", "WebFetch", "WebSearch",
    "NotebookEdit", "AskUserQuestion", "EnterPlanMode", "ExitPlanMode",
    "Skill", "TaskStop",
})


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def extract_retrieval_metrics(
    task_dir: str | Path,
    oracle_items: list[dict],
) -> dict:
    """Extract context retrieval KPIs from agent logs.

    Works for both baseline (local tools: Read/Grep/Glob/Bash) and MCP
    configs (mcp__* prefixed tool calls).  Oracle coverage counts items
    found via ANY tool — baseline CAN score non-zero for local checkouts.

    Args:
        task_dir: Path to the Harbor task output directory.  Must contain
            ``agent/trajectory.json`` or ``agent/claude-code.txt``.
        oracle_items: Oracle items to match against.  Each item is a dict
            with ``type`` (``'file'``/``'symbol'``), ``repo``, ``path``,
            and optionally ``symbol``.  Obtain via :func:`load_oracle_items`.

    Returns:
        Dict with keys:

        - ``oracle_coverage`` (float 0.0–1.0): fraction of oracle items found
        - ``oracle_items_found`` (int): absolute count of items found
        - ``oracle_items_total`` (int): total oracle items
        - ``time_to_first_oracle_hit_ms`` (float|None): ms from first tool
          call with a timestamp to the first oracle hit
        - ``unique_repos_touched`` (int): distinct repos accessed
        - ``unique_orgs_touched`` (int): distinct orgs accessed
        - ``tool_call_counts`` (dict[str,int]): call count per tool name
        - ``mcp_tool_counts`` (dict[str,int]): MCP-only subset
        - ``local_tool_counts`` (dict[str,int]): local-tools-only subset

    >>> extract_retrieval_metrics("/nonexistent", [])
    {'oracle_coverage': 0.0, 'oracle_items_found': 0, 'oracle_items_total': 0, 'time_to_first_oracle_hit_ms': None, 'unique_repos_touched': 0, 'unique_orgs_touched': 0, 'tool_call_counts': {}, 'mcp_tool_counts': {}, 'local_tool_counts': {}}
    """
    task_dir = Path(task_dir)
    n_items = len(oracle_items)

    empty: dict = {
        "oracle_coverage": 0.0,
        "oracle_items_found": 0,
        "oracle_items_total": n_items,
        "time_to_first_oracle_hit_ms": None,
        "unique_repos_touched": 0,
        "unique_orgs_touched": 0,
        "tool_call_counts": {},
        "mcp_tool_counts": {},
        "local_tool_counts": {},
    }

    tool_calls = _load_tool_calls(task_dir)
    if not tool_calls:
        return empty

    # Start time = first tool call that carries a timestamp
    start_time: Optional[datetime] = None
    for _, _, ts in tool_calls:
        t = _parse_iso(ts)
        if t is not None:
            start_time = t
            break

    hit_indices: set[int] = set()
    first_hit_time: Optional[datetime] = None
    repos_touched: set[str] = set()
    orgs_touched: set[str] = set()
    tool_counts: dict[str, int] = {}
    mcp_counts: dict[str, int] = {}
    local_counts: dict[str, int] = {}

    for tool_name, args, ts in tool_calls:
        # ── count ──────────────────────────────────────────────────────────
        tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
        if tool_name.startswith("mcp__"):
            mcp_counts[tool_name] = mcp_counts.get(tool_name, 0) + 1
        elif tool_name in _LOCAL_TOOLS:
            local_counts[tool_name] = local_counts.get(tool_name, 0) + 1

        # ── repos touched ──────────────────────────────────────────────────
        repo = _extract_repo_from_tool_call(tool_name, args)
        if repo:
            repos_touched.add(repo)
            org = _extract_org_from_repo(repo)
            if org:
                orgs_touched.add(org)

        # ── oracle hit detection ───────────────────────────────────────────
        call_time = _parse_iso(ts)
        is_mcp = tool_name.startswith("mcp__")
        for i, item in enumerate(oracle_items):
            if i in hit_indices:
                continue
            hit = (
                _check_mcp_tool_hit(tool_name, args, item)
                if is_mcp
                else _check_local_tool_hit(tool_name, args, item)
            )
            if hit:
                hit_indices.add(i)
                if first_hit_time is None:
                    first_hit_time = call_time

    # ── aggregate ─────────────────────────────────────────────────────────
    n_found = len(hit_indices)
    coverage = n_found / n_items if n_items > 0 else 0.0

    ttfh_ms: Optional[float] = None
    if start_time is not None and first_hit_time is not None:
        delta = (first_hit_time - start_time).total_seconds() * 1000
        ttfh_ms = round(max(0.0, delta), 1)

    return {
        "oracle_coverage": round(coverage, 4),
        "oracle_items_found": n_found,
        "oracle_items_total": n_items,
        "time_to_first_oracle_hit_ms": ttfh_ms,
        "unique_repos_touched": len(repos_touched),
        "unique_orgs_touched": len(orgs_touched),
        "tool_call_counts": dict(sorted(tool_counts.items())),
        "mcp_tool_counts": dict(sorted(mcp_counts.items())),
        "local_tool_counts": dict(sorted(local_counts.items())),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _find_task_spec(task_dir: Path) -> Optional[Path]:
    """Search for task_spec.json in common locations under *task_dir*."""
    for rel in ("tests/task_spec.json", "task_spec.json"):
        p = task_dir / rel
        if p.is_file():
            return p
    return None


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point.

    Returns 0 on success, 1 on error.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract MCP retrieval metrics from a Harbor task output directory.",
    )
    parser.add_argument(
        "--task-dir",
        required=True,
        help="Path to the Harbor task output directory (contains agent/claude-code.txt or agent/trajectory.json).",
    )
    parser.add_argument(
        "--task-spec",
        default=None,
        help="Path to task_spec.json to load oracle items from. "
             "Defaults to <task_dir>/tests/task_spec.json.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for retrieval_metrics.json. "
             "Defaults to <task_dir>/retrieval_metrics.json.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print metrics to stdout.",
    )
    args = parser.parse_args(argv)

    task_dir = Path(args.task_dir)

    # Locate task_spec
    spec_path: Optional[Path] = None
    if args.task_spec:
        spec_path = Path(args.task_spec)
    else:
        spec_path = _find_task_spec(task_dir)

    oracle_items: list[dict] = []
    if spec_path is not None:
        oracle_items = load_oracle_items(spec_path)
        if args.verbose:
            print(f"Loaded {len(oracle_items)} oracle items from {spec_path}", file=sys.stderr)
    else:
        if args.verbose:
            print("No task_spec.json found — oracle_coverage will be 0.", file=sys.stderr)

    metrics = extract_retrieval_metrics(task_dir, oracle_items)

    out_path = Path(args.output) if args.output else task_dir / "retrieval_metrics.json"
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(metrics, indent=2))
        if args.verbose:
            print(f"Wrote metrics to {out_path}", file=sys.stderr)
    except OSError as exc:
        print(f"Error writing {out_path}: {exc}", file=sys.stderr)
        return 1

    if args.verbose:
        print(json.dumps(metrics, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
