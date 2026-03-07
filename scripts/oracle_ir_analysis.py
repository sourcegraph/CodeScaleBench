#!/usr/bin/env python3
"""Oracle-based IR analysis for org-scale benchmark tasks.

Computes retrieval quality metrics (precision, recall, MRR, nDCG, MAP,
context efficiency, time-to-context) using oracle ground truth from
task_spec.json instead of file-change diffs.

Uses csb_metrics.retrieval for oracle item loading and tool call extraction,
and csb_metrics.ir_metrics for pure IR math functions.

Usage:
    # Analyze staging org-scale runs (default)
    python3 scripts/oracle_ir_analysis.py

    # JSON output
    python3 scripts/oracle_ir_analysis.py --json

    # Per-task detail
    python3 scripts/oracle_ir_analysis.py --per-task

    # Custom runs directory
    python3 scripts/oracle_ir_analysis.py --runs-dir runs/staging

    # Filter by suite
    python3 scripts/oracle_ir_analysis.py --suite ccb_mcp_crossrepo_tracing
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Ensure scripts/ is on path for csb_metrics imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from csb_metrics.retrieval import (
    load_oracle_items,
    extract_retrieval_metrics,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
STAGING_DIR = REPO_ROOT / "runs" / "staging"
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
SELECTION_FILE = REPO_ROOT / "configs" / "selected_mcp_unique_tasks.json"

SKIP_PATTERNS = ["__broken_verifier", "validation_test", "archive", "__archived"]

# Config names for baseline and MCP
BASELINE_CONFIGS = {"baseline-local-artifact", "baseline-local-direct", "baseline"}
MCP_CONFIGS = {"mcp-remote-artifact", "mcp-remote-direct", "sourcegraph_full"}

# Hosting prefix regex for repo normalization
_HOSTING_PREFIX_RE = re.compile(r"^(?:github\.com|gitlab\.com|bitbucket\.org|sourcegraph\.com)/")


# ---------------------------------------------------------------------------
# IR math functions (self-contained, matching ir_metrics.py semantics)
# ---------------------------------------------------------------------------

def _normalize_item(repo: str, path: str) -> tuple[str, str]:
    """Normalize repo and path for comparison."""
    repo = _HOSTING_PREFIX_RE.sub("", repo.strip()).strip("/")
    path = path.strip().strip("/").lower()
    # Strip /workspace/ prefix from local paths
    if path.startswith("workspace/"):
        path = path[len("workspace/"):]
    return repo.lower(), path


def precision_at_k(retrieved: list[tuple], relevant: set[tuple], k: int) -> float:
    if k <= 0:
        return 0.0
    top_k = retrieved[:k]
    hits = sum(1 for item in top_k if item in relevant)
    return hits / k


def recall_at_k(retrieved: list[tuple], relevant: set[tuple], k: int) -> float:
    if not relevant:
        return 1.0
    if k <= 0:
        return 0.0
    top_k = retrieved[:k]
    hits = sum(1 for item in top_k if item in relevant)
    return hits / len(relevant)


def f1_at_k(retrieved: list[tuple], relevant: set[tuple], k: int) -> float:
    p = precision_at_k(retrieved, relevant, k)
    r = recall_at_k(retrieved, relevant, k)
    return (2 * p * r / (p + r)) if (p + r) > 0 else 0.0


def mrr(retrieved: list[tuple], relevant: set[tuple]) -> float:
    for i, item in enumerate(retrieved):
        if item in relevant:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(retrieved: list[tuple], relevant: set[tuple], k: int) -> float:
    if k <= 0 or not relevant:
        return 0.0
    dcg = sum(
        1.0 / math.log2(i + 2)
        for i, item in enumerate(retrieved[:k])
        if item in relevant
    )
    ideal_k = min(k, len(relevant))
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_k))
    return dcg / idcg if idcg > 0 else 0.0


def ndcg_graded(retrieved: list[tuple], chain_steps: list[tuple], k: int) -> float:
    """nDCG with graded relevance from dependency chain position.

    Earlier chain steps get higher relevance: step 0 has relevance N,
    step 1 has N-1, etc.
    """
    if k <= 0 or not chain_steps:
        return 0.0
    n = len(chain_steps)
    relevance = {}
    for idx, step in enumerate(chain_steps):
        relevance[step] = n - idx  # first step = highest relevance

    dcg = 0.0
    for i, item in enumerate(retrieved[:k]):
        rel = relevance.get(item, 0)
        if rel > 0:
            dcg += rel / math.log2(i + 2)

    # Ideal: chain steps sorted by relevance (first step first)
    ideal_rels = sorted(relevance.values(), reverse=True)[:k]
    idcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(ideal_rels))
    return dcg / idcg if idcg > 0 else 0.0


def mean_average_precision(retrieved: list[tuple], relevant: set[tuple]) -> float:
    if not relevant:
        return 1.0
    hits = 0
    sum_prec = 0.0
    for i, item in enumerate(retrieved):
        if item in relevant:
            hits += 1
            sum_prec += hits / (i + 1)
    return sum_prec / len(relevant) if relevant else 0.0


def file_level_recall(retrieved: list[tuple], relevant: set[tuple]) -> float:
    if not relevant:
        return 1.0
    found = sum(1 for item in relevant if item in set(retrieved))
    return found / len(relevant)


def context_efficiency(retrieved: list[tuple], relevant: set[tuple]) -> float:
    if not retrieved:
        return 0.0
    hits = sum(1 for item in retrieved if item in relevant)
    return hits / len(retrieved)


# ---------------------------------------------------------------------------
# Transcript parsing — extract ordered (repo, path) retrieval sequence
# ---------------------------------------------------------------------------

# MCP tool patterns
_MCP_TOOL_RE = re.compile(
    r'"name"\s*:\s*"mcp__sourcegraph__(?:sg_)?(\w+)"'
)
# Path extraction from tool results
_PATH_JSON_RE = re.compile(r'"path"\s*:\s*"([^"]+)"')
_REPO_JSON_RE = re.compile(r'"repo"\s*:\s*"([^"]+)"')

# Local tools that access files
_LOCAL_READ_TOOLS = {"Read", "read"}
_LOCAL_SEARCH_TOOLS = {"Grep", "Glob", "grep", "glob"}

# MCP tools that directly access a specific file
_MCP_READ_TOOLS = {"read_file", "sg_read_file"}
_MCP_SYMBOL_TOOLS = {"find_references", "sg_find_references",
                      "go_to_definition", "sg_go_to_definition"}
_MCP_SEARCH_TOOLS = {"keyword_search", "sg_keyword_search",
                      "nls_search", "sg_nls_search",
                      "list_files", "sg_list_files"}


def _parse_tool_input(entry: dict) -> Optional[dict]:
    """Extract tool name and input from a JSONL entry."""
    # Harbor nested format: content[] with tool_use blocks
    content = entry.get("content", [])
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                return {
                    "name": block.get("name", ""),
                    "input": block.get("input", block.get("arguments", {})),
                }
    # Top-level tool_use
    if entry.get("type") == "tool_use":
        return {
            "name": entry.get("name", ""),
            "input": entry.get("input", entry.get("arguments", {})),
        }
    return None


def _parse_tool_result(entry: dict) -> Optional[str]:
    """Extract tool result content text from a JSONL entry."""
    content = entry.get("content", [])
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                inner = block.get("content", "")
                if isinstance(inner, str):
                    return inner
                if isinstance(inner, list):
                    texts = [b.get("text", "") for b in inner if isinstance(b, dict)]
                    return "\n".join(texts)
    if entry.get("type") == "tool_result":
        inner = entry.get("content", "")
        if isinstance(inner, str):
            return inner
    return None


def extract_retrieval_sequence(transcript_path: Path) -> list[dict]:
    """Extract ordered sequence of retrieved (repo, path) items from transcript.

    Handles the Harbor JSONL format where tool_use blocks are nested:
        {"type": "assistant", "message": {"content": [{"type": "tool_use", ...}]}}
    and tool_result blocks appear in user messages:
        {"type": "user", "message": {"content": [{"type": "tool_result", ...}]}}

    Returns list of dicts: {repo, path, tool, step_index, is_mcp}
    Each unique (repo, path) appears only at its first occurrence.
    """
    if not transcript_path.is_file():
        return []

    retrievals: list[dict] = []
    seen: set[tuple[str, str]] = set()
    step = 0

    # Track pending tool calls by ID for matching with results
    pending_tools: dict[str, dict] = {}  # tool_use_id -> {name, input, step}

    def _add_retrieval(repo: str, path: str, tool: str, is_mcp: bool):
        key = _normalize_item(repo, path)
        if key[0] or key[1]:  # at least one non-empty
            if key not in seen:
                seen.add(key)
                retrievals.append({
                    "repo": key[0], "path": key[1],
                    "tool": tool, "step": step,
                    "is_mcp": is_mcp,
                })

    def _extract_content_blocks(entry: dict) -> list[dict]:
        """Get content blocks from either nested or top-level format."""
        # Harbor format: entry["message"]["content"]
        msg = entry.get("message", {})
        if isinstance(msg, dict):
            c = msg.get("content", [])
            if isinstance(c, list):
                return [b for b in c if isinstance(b, dict)]
        # Fallback: entry["content"]
        c = entry.get("content", [])
        if isinstance(c, list):
            return [b for b in c if isinstance(b, dict)]
        return []

    def _extract_result_text(block: dict) -> str:
        """Extract text content from a tool_result block."""
        inner = block.get("content", "")
        if isinstance(inner, str):
            return inner
        if isinstance(inner, list):
            return "\n".join(
                b.get("text", "") for b in inner if isinstance(b, dict)
            )
        return ""

    try:
        with open(transcript_path, "r", errors="replace") as f:
            for line_num, raw_line in enumerate(f):
                if len(raw_line) > 1_000_000:
                    raw_line = raw_line[:1_000_000]
                try:
                    entry = json.loads(raw_line.strip())
                except (json.JSONDecodeError, ValueError):
                    continue

                entry_type = entry.get("type", "")

                # Skip system init lines
                if entry_type == "system":
                    continue

                blocks = _extract_content_blocks(entry)

                for block in blocks:
                    block_type = block.get("type", "")

                    if block_type == "tool_use":
                        tool_name = block.get("name", "")
                        tool_input = block.get("input", {}) or {}
                        tool_id = block.get("id", "")

                        if tool_id:
                            pending_tools[tool_id] = {
                                "name": tool_name,
                                "input": tool_input,
                                "step": step,
                            }

                        base_name = re.sub(
                            r"^mcp__sourcegraph__(?:sg_)?", "", tool_name
                        )

                        if base_name in _MCP_READ_TOOLS:
                            repo = tool_input.get("repo", "")
                            path = tool_input.get("path", "")
                            if repo and path:
                                _add_retrieval(repo, path, base_name, True)

                        elif base_name in _MCP_SYMBOL_TOOLS:
                            repo = tool_input.get("repo", "")
                            path = tool_input.get("path", "")
                            if repo and path:
                                _add_retrieval(repo, path, base_name, True)

                        elif base_name in _MCP_SEARCH_TOOLS:
                            # Search tools: also extract repo+path from INPUT
                            # (e.g., sg_list_files has repo and path args)
                            repo = tool_input.get("repo", "")
                            path = tool_input.get("path", "")
                            # list_files input path is a directory, not a file
                            # Don't add as retrieval here; wait for results

                        elif tool_name == "Read":
                            file_path = tool_input.get("file_path", "")
                            if file_path:
                                norm_path = file_path.strip().lower()
                                for prefix in ["/workspace/", "workspace/"]:
                                    if norm_path.startswith(prefix):
                                        norm_path = norm_path[len(prefix):]
                                        break
                                norm_path = norm_path.strip("/")
                                _add_retrieval("", norm_path, "Read", False)

                        elif tool_name == "Bash":
                            # Extract file paths from bash commands
                            cmd = tool_input.get("command", "")
                            # Don't parse bash commands for retrievals here;
                            # will be handled via tool_result if they produce output

                        step += 1

                    elif block_type == "tool_result":
                        tool_id = block.get("tool_use_id", "")
                        result_text = _extract_result_text(block)

                        tool_info = pending_tools.pop(tool_id, None)
                        if not tool_info or not result_text:
                            continue

                        base = re.sub(
                            r"^mcp__sourcegraph__(?:sg_)?", "",
                            tool_info["name"],
                        )

                        if base in _MCP_SEARCH_TOOLS:
                            # Extract (repo, path) from search result content
                            # MCP search results contain JSON with repo+path
                            chunk = result_text[:100_000]
                            repos_found = _REPO_JSON_RE.findall(chunk)
                            paths_found = _PATH_JSON_RE.findall(chunk)

                            if repos_found and paths_found:
                                # Results have both repo and path (keyword_search, nls_search)
                                for r, p in zip(repos_found, paths_found):
                                    _add_retrieval(r, p, base + "_result", True)
                            elif paths_found and not repos_found:
                                # Results have paths only (sg_list_files) —
                                # carry repo from the tool_use INPUT
                                input_repo = tool_info["input"].get("repo", "")
                                for p in paths_found:
                                    if input_repo and p:
                                        _add_retrieval(input_repo, p, base + "_result", True)

                        elif base in _MCP_READ_TOOLS:
                            # Read results may reference other files
                            pass

                        elif tool_info["name"] == "Bash":
                            # Extract file paths from bash output
                            # Look for lines that look like file paths
                            for out_line in result_text.splitlines()[:200]:
                                out_line = out_line.strip()
                                # Match common grep/find output patterns
                                # e.g., "dynamic/client_test.go:import ..."
                                if ":" in out_line:
                                    candidate = out_line.split(":")[0].strip()
                                elif out_line.startswith("./"):
                                    candidate = out_line[2:]
                                elif "/" in out_line and "." in out_line:
                                    candidate = out_line
                                else:
                                    continue
                                # Filter: must look like a file path
                                if "/" in candidate and "." in candidate:
                                    norm = candidate.lower().strip("/")
                                    for prefix in ["workspace/", "/workspace/"]:
                                        if norm.startswith(prefix):
                                            norm = norm[len(prefix):]
                                    # Skip obviously non-path strings
                                    if len(norm) < 200 and " " not in norm:
                                        _add_retrieval("", norm, "Bash_result", False)

                        elif tool_info["name"] in ("Grep", "Glob"):
                            # Extract file paths from search results
                            for out_line in result_text.splitlines()[:200]:
                                out_line = out_line.strip()
                                if "/" in out_line and "." in out_line:
                                    candidate = out_line.split(":")[0].strip() if ":" in out_line else out_line
                                    norm = candidate.lower().strip("/")
                                    for prefix in ["workspace/", "/workspace/"]:
                                        if norm.startswith(prefix):
                                            norm = norm[len(prefix):]
                                    if len(norm) < 200 and " " not in norm:
                                        _add_retrieval("", norm, tool_info["name"] + "_result", False)

    except OSError:
        pass

    return retrievals


# ---------------------------------------------------------------------------
# Task directory walker
# ---------------------------------------------------------------------------

def _is_batch_timestamp(name: str) -> bool:
    return bool(re.match(r"\d{4}-\d{2}-\d{2}__\d{2}-\d{2}-\d{2}", name))


def _extract_task_id(dirname: str) -> str:
    """Strip __hash suffix from directory name to get task ID."""
    if "__" in dirname:
        parts = dirname.rsplit("__", 1)
        if len(parts) == 2 and len(parts[1]) >= 6:
            return parts[0]
    return dirname


def _detect_suite(run_dir_name: str) -> Optional[str]:
    """Detect org-scale suite from run directory name."""
    m = re.match(r"((?:csb_org|ccb_mcp)_\w+?)_\w+_\d{8}_\d{6}", run_dir_name)
    if m:
        return m.group(1)
    return None


def _is_config_dir(name: str) -> bool:
    return name in BASELINE_CONFIGS | MCP_CONFIGS


def _config_type(name: str) -> str:
    if name in BASELINE_CONFIGS:
        return "baseline"
    if name in MCP_CONFIGS:
        return "mcp"
    return "unknown"


def walk_org_runs(runs_dir: Path, suite_filter: str = "") -> list[dict]:
    """Walk org-scale run directories and collect task info.

    Returns list of dicts: {task_id, suite, config, config_type, task_dir,
    transcript, result_path, reward}
    """
    tasks = []

    if not runs_dir.exists():
        return tasks

    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        if any(pat in run_dir.name for pat in SKIP_PATTERNS):
            continue
        # Only org-scale runs
        if "ccb_mcp_" not in run_dir.name and "csb_org_" not in run_dir.name:
            continue

        suite = _detect_suite(run_dir.name)
        if not suite:
            continue
        if suite_filter and suite != suite_filter:
            continue

        for config_dir in sorted(run_dir.iterdir()):
            if not config_dir.is_dir() or not _is_config_dir(config_dir.name):
                continue

            config_name = config_dir.name
            ctype = _config_type(config_name)

            for batch_dir in sorted(config_dir.iterdir()):
                if not batch_dir.is_dir() or not _is_batch_timestamp(batch_dir.name):
                    continue

                for task_dir in sorted(batch_dir.iterdir()):
                    if not task_dir.is_dir():
                        continue

                    task_id = _extract_task_id(task_dir.name)

                    # Find transcript
                    transcript = task_dir / "agent" / "claude-code.txt"
                    if not transcript.is_file():
                        transcript = task_dir / "claude-code.txt"

                    # Find result
                    result_path = task_dir / "result.json"
                    reward = None
                    started_at = ""
                    agent_exec_secs = None
                    if result_path.is_file():
                        try:
                            rdata = json.loads(result_path.read_text())
                            started_at = rdata.get("started_at", "")
                            vr = rdata.get("verifier_result") or {}
                            rewards = vr.get("rewards") or {}
                            r = rewards.get("reward", rewards.get("score"))
                            if r is not None:
                                reward = float(r)
                            ae = rdata.get("agent_execution") or {}
                            ae_start = ae.get("started_at", "")
                            ae_end = ae.get("finished_at", "")
                            if ae_start and ae_end:
                                try:
                                    s = datetime.fromisoformat(ae_start.replace("Z", "+00:00"))
                                    e = datetime.fromisoformat(ae_end.replace("Z", "+00:00"))
                                    agent_exec_secs = (e - s).total_seconds()
                                except (ValueError, TypeError):
                                    pass
                        except (json.JSONDecodeError, OSError):
                            pass

                    tasks.append({
                        "task_id": task_id,
                        "suite": suite,
                        "config": config_name,
                        "config_type": ctype,
                        "task_dir": str(task_dir),
                        "transcript": str(transcript) if transcript.is_file() else None,
                        "result_path": str(result_path) if result_path.is_file() else None,
                        "reward": reward,
                        "started_at": started_at,
                        "agent_exec_secs": agent_exec_secs,
                    })

    # Dedup by (suite, config, task_id) — keep latest by started_at
    deduped: dict[tuple, dict] = {}
    for t in tasks:
        key = (t["suite"], t["config"], t["task_id"])
        if key not in deduped or t["started_at"] > deduped[key]["started_at"]:
            deduped[key] = t

    return list(deduped.values())


# ---------------------------------------------------------------------------
# Find task_spec.json for a given task
# ---------------------------------------------------------------------------

def _find_task_spec(task_id: str) -> Optional[Path]:
    """Locate task_spec.json in benchmarks/ for a given task_id."""
    # Search all csb_org_* / ccb_mcp_* suites
    for suite_dir in BENCHMARKS_DIR.iterdir():
        if not suite_dir.is_dir() or not suite_dir.name.startswith(("csb_org_", "ccb_mcp_")):
            continue
        task_dir = suite_dir / task_id
        spec = task_dir / "tests" / "task_spec.json"
        if spec.is_file():
            return spec
    return None


# ---------------------------------------------------------------------------
# Compute oracle IR scores for a single task
# ---------------------------------------------------------------------------

def compute_oracle_ir(
    task_id: str,
    config_name: str,
    task_dir: str,
    transcript_path: Optional[str],
    task_spec_path: Path,
) -> dict[str, Any]:
    """Compute oracle-based IR metrics for one task run.

    Returns dict with: precision@K, recall@K, F1@K, MRR, nDCG@K, MAP,
    file_level_recall, context_efficiency, time-to-context, oracle_coverage.
    """
    result: dict[str, Any] = {
        "task_id": task_id,
        "config": config_name,
    }

    # Load oracle ground truth
    spec_data = json.loads(task_spec_path.read_text())
    oracle = (spec_data.get("artifacts") or {}).get("oracle") or {}

    # Build ground truth sets
    file_gt: set[tuple[str, str]] = set()
    symbol_gt: set[tuple[str, str, str]] = set()
    chain_steps: list[tuple[str, str, str]] = []

    for f in oracle.get("required_files") or []:
        key = _normalize_item(f.get("repo", ""), f.get("path", ""))
        file_gt.add(key)

    for s in oracle.get("required_symbols") or []:
        key = _normalize_item(s.get("repo", ""), s.get("path", ""))
        file_gt.add(key)  # also a file-level ground truth
        sym = s.get("symbol", "").lower()
        symbol_gt.add((key[0], key[1], sym))

    for chain in oracle.get("dependency_chains") or []:
        for step in chain.get("steps") or []:
            key = _normalize_item(step.get("repo", ""), step.get("path", ""))
            file_gt.add(key)
            sym = step.get("symbol", "").lower()
            chain_steps.append((key[0], key[1], sym))
            symbol_gt.add((key[0], key[1], sym))

    result["n_ground_truth_files"] = len(file_gt)
    result["n_ground_truth_symbols"] = len(symbol_gt)
    result["n_chain_steps"] = len(chain_steps)

    if not file_gt and not symbol_gt:
        result["skipped"] = "no_oracle_items"
        return result

    # Extract retrieval sequence from transcript
    if not transcript_path or not Path(transcript_path).is_file():
        result["skipped"] = "no_transcript"
        return result

    retrievals = extract_retrieval_sequence(Path(transcript_path))
    result["n_retrieved"] = len(retrievals)
    result["n_mcp_retrievals"] = sum(1 for r in retrievals if r["is_mcp"])
    result["n_local_retrievals"] = sum(1 for r in retrievals if not r["is_mcp"])

    # Build retrieved list as (repo, path) tuples
    retrieved_files = [(r["repo"], r["path"]) for r in retrievals]

    # For baseline: local tools have empty repo. Match by path suffix
    # against any oracle repo. Build an expanded retrieval list.
    retrieved_matched: list[tuple[str, str]] = []
    for repo, path in retrieved_files:
        if repo:
            retrieved_matched.append((repo, path))
        else:
            # Local tool: try matching path suffix against all oracle items
            matched = False
            for gt_repo, gt_path in file_gt:
                if path and gt_path.lower().endswith(path) or path.endswith(gt_path):
                    retrieved_matched.append((gt_repo, gt_path))
                    matched = True
                    break
            if not matched:
                retrieved_matched.append(("", path))

    # Deduplicate while preserving order
    seen_rm: set[tuple] = set()
    deduped_retrieved: list[tuple] = []
    for item in retrieved_matched:
        if item not in seen_rm:
            seen_rm.add(item)
            deduped_retrieved.append(item)

    k_values = [1, 3, 5, 10]

    # File-level IR metrics
    result["file_recall"] = round(file_level_recall(deduped_retrieved, file_gt), 4)
    result["file_mrr"] = round(mrr(deduped_retrieved, file_gt), 4)
    result["file_map"] = round(mean_average_precision(deduped_retrieved, file_gt), 4)
    result["context_efficiency"] = round(context_efficiency(deduped_retrieved, file_gt), 4)

    for k in k_values:
        result[f"file_precision@{k}"] = round(precision_at_k(deduped_retrieved, file_gt, k), 4)
        result[f"file_recall@{k}"] = round(recall_at_k(deduped_retrieved, file_gt, k), 4)
        result[f"file_f1@{k}"] = round(f1_at_k(deduped_retrieved, file_gt, k), 4)
        result[f"file_ndcg@{k}"] = round(ndcg_at_k(deduped_retrieved, file_gt, k), 4)

    # Overlap details
    overlap = file_gt & set(deduped_retrieved)
    missing = file_gt - set(deduped_retrieved)
    result["n_overlap"] = len(overlap)
    result["missing_files"] = [{"repo": r, "path": p} for r, p in sorted(missing)]

    # Chain nDCG (graded relevance from position)
    if chain_steps:
        # Build retrieved as (repo, path, symbol) for chain matching
        retrieved_symbols = []
        for r in retrievals:
            retrieved_symbols.append((r["repo"], r["path"], ""))
        result["chain_ndcg@5"] = round(ndcg_graded(retrieved_symbols, chain_steps, 5), 4)
        result["chain_ndcg@10"] = round(ndcg_graded(retrieved_symbols, chain_steps, 10), 4)

    # Time-to-first-relevant (step-based)
    # Use suffix matching for baseline (empty repo) just like the retrieval matching above
    first_relevant_step = None
    for r in retrievals:
        r_repo, r_path = _normalize_item(r["repo"], r["path"])
        matched = False
        if r_repo:
            # MCP: exact match
            if (r_repo, r_path) in file_gt:
                matched = True
        else:
            # Baseline: suffix match against any oracle file
            for gt_repo, gt_path in file_gt:
                if r_path and (gt_path.endswith(r_path) or r_path.endswith(gt_path)):
                    matched = True
                    break
        if matched:
            first_relevant_step = r["step"]
            result["first_relevant_tool"] = r["tool"]
            break
    result["steps_to_first_relevant"] = first_relevant_step

    # Also get retrieval metrics from the retrieval.py module (oracle coverage + TTFH)
    oracle_items = load_oracle_items(task_spec_path)
    if oracle_items:
        ret_metrics = extract_retrieval_metrics(task_dir, oracle_items)
        result["oracle_coverage"] = ret_metrics.get("oracle_coverage", 0.0)
        result["oracle_items_found"] = ret_metrics.get("oracle_items_found", 0)
        result["oracle_items_total"] = ret_metrics.get("oracle_items_total", 0)
        result["time_to_first_oracle_hit_ms"] = ret_metrics.get("time_to_first_oracle_hit_ms")
        result["unique_repos_touched"] = ret_metrics.get("unique_repos_touched", 0)
        result["unique_orgs_touched"] = ret_metrics.get("unique_orgs_touched", 0)
        result["mcp_tool_counts"] = ret_metrics.get("mcp_tool_counts", {})
        result["local_tool_counts"] = ret_metrics.get("local_tool_counts", {})

    return result


# ---------------------------------------------------------------------------
# Aggregate and compare
# ---------------------------------------------------------------------------

def aggregate_scores(task_scores: list[dict]) -> dict:
    """Aggregate per-task scores into summary statistics."""
    if not task_scores:
        return {}

    metrics_to_agg = [
        "file_recall", "file_mrr", "file_map", "context_efficiency",
        "oracle_coverage", "steps_to_first_relevant",
    ]
    # Add @K metrics
    for k in [1, 3, 5, 10]:
        metrics_to_agg.extend([
            f"file_precision@{k}", f"file_recall@{k}",
            f"file_f1@{k}", f"file_ndcg@{k}",
        ])

    agg: dict[str, Any] = {"n_tasks": len(task_scores)}

    for metric in metrics_to_agg:
        values = [t[metric] for t in task_scores if metric in t and t[metric] is not None]
        if values:
            agg[metric] = {
                "mean": round(statistics.mean(values), 4),
                "median": round(statistics.median(values), 4),
                "std": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
                "n": len(values),
            }

    # Time-to-first-oracle-hit
    ttfh_values = [
        t["time_to_first_oracle_hit_ms"]
        for t in task_scores
        if t.get("time_to_first_oracle_hit_ms") is not None
    ]
    if ttfh_values:
        agg["time_to_first_oracle_hit_ms"] = {
            "mean": round(statistics.mean(ttfh_values), 1),
            "median": round(statistics.median(ttfh_values), 1),
            "n": len(ttfh_values),
        }

    return agg


def compare_configs(
    baseline_scores: list[dict],
    mcp_scores: list[dict],
) -> dict:
    """Compare baseline vs MCP IR scores per-task and aggregate."""
    # Index by task_id
    bl_by_task = {t["task_id"]: t for t in baseline_scores}
    mcp_by_task = {t["task_id"]: t for t in mcp_scores}

    common_tasks = sorted(set(bl_by_task) & set(mcp_by_task))

    deltas = []
    per_task = []
    for tid in common_tasks:
        bl = bl_by_task[tid]
        mc = mcp_by_task[tid]

        metrics = ["file_recall", "file_mrr", "file_map", "context_efficiency", "oracle_coverage"]
        delta = {"task_id": tid}
        for m in metrics:
            bv = bl.get(m)
            mv = mc.get(m)
            if bv is not None and mv is not None:
                delta[f"{m}_bl"] = bv
                delta[f"{m}_mcp"] = mv
                delta[f"{m}_delta"] = round(mv - bv, 4)

        # Steps efficiency
        bl_steps = bl.get("steps_to_first_relevant")
        mc_steps = mc.get("steps_to_first_relevant")
        if bl_steps is not None and mc_steps is not None:
            delta["steps_bl"] = bl_steps
            delta["steps_mcp"] = mc_steps

        deltas.append(delta)
        per_task.append(delta)

    # Aggregate deltas
    agg_deltas: dict[str, Any] = {"n_common_tasks": len(common_tasks)}
    for m in ["file_recall", "file_mrr", "file_map", "context_efficiency", "oracle_coverage"]:
        dvals = [d[f"{m}_delta"] for d in deltas if f"{m}_delta" in d]
        if dvals:
            agg_deltas[f"{m}_delta"] = {
                "mean": round(statistics.mean(dvals), 4),
                "median": round(statistics.median(dvals), 4),
                "wins": sum(1 for d in dvals if d > 0),
                "losses": sum(1 for d in dvals if d < 0),
                "ties": sum(1 for d in dvals if d == 0),
            }

    return {
        "per_task": per_task,
        "aggregate_deltas": agg_deltas,
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_report(
    baseline_agg: dict,
    mcp_agg: dict,
    comparison: dict,
    per_task_bl: list[dict],
    per_task_mcp: list[dict],
    show_per_task: bool = False,
) -> str:
    """Format human-readable report."""
    lines = []
    lines.append("=" * 70)
    lines.append("Oracle IR Analysis — MCP-Unique Tasks")
    lines.append("=" * 70)

    # Aggregate comparison table
    lines.append("")
    lines.append("AGGREGATE METRICS")
    lines.append("-" * 70)
    header = f"{'Metric':<30} {'Baseline':>10} {'MCP':>10} {'Delta':>10} {'W/L/T':>10}"
    lines.append(header)
    lines.append("-" * 70)

    metrics_display = [
        ("File Recall", "file_recall"),
        ("MRR", "file_mrr"),
        ("MAP", "file_map"),
        ("Context Efficiency", "context_efficiency"),
        ("Oracle Coverage", "oracle_coverage"),
    ]

    for label, key in metrics_display:
        bl_val = baseline_agg.get(key, {}).get("mean", "—")
        mc_val = mcp_agg.get(key, {}).get("mean", "—")
        delta_info = comparison.get("aggregate_deltas", {}).get(f"{key}_delta", {})
        delta = delta_info.get("mean", "—")
        wlt = ""
        if isinstance(delta_info, dict) and "wins" in delta_info:
            w, l, t = delta_info["wins"], delta_info["losses"], delta_info["ties"]
            wlt = f"{w}/{l}/{t}"

        bl_s = f"{bl_val:.4f}" if isinstance(bl_val, float) else str(bl_val)
        mc_s = f"{mc_val:.4f}" if isinstance(mc_val, float) else str(mc_val)
        d_s = f"{delta:+.4f}" if isinstance(delta, float) else str(delta)
        lines.append(f"{label:<30} {bl_s:>10} {mc_s:>10} {d_s:>10} {wlt:>10}")

    # @K metrics
    lines.append("")
    lines.append("PRECISION / RECALL / nDCG @ K")
    lines.append("-" * 70)
    header2 = f"{'Metric':<20} {'K':>3} {'BL':>10} {'MCP':>10} {'Delta':>10}"
    lines.append(header2)
    lines.append("-" * 70)
    for metric_name, key_prefix in [("Precision", "file_precision"), ("Recall", "file_recall"),
                                     ("nDCG", "file_ndcg"), ("F1", "file_f1")]:
        for k in [1, 3, 5, 10]:
            key = f"{key_prefix}@{k}"
            bl_val = baseline_agg.get(key, {}).get("mean", "—")
            mc_val = mcp_agg.get(key, {}).get("mean", "—")
            delta = (mc_val - bl_val) if isinstance(bl_val, float) and isinstance(mc_val, float) else "—"
            bl_s = f"{bl_val:.4f}" if isinstance(bl_val, float) else str(bl_val)
            mc_s = f"{mc_val:.4f}" if isinstance(mc_val, float) else str(mc_val)
            d_s = f"{delta:+.4f}" if isinstance(delta, float) else str(delta)
            lines.append(f"{metric_name:<20} {k:>3} {bl_s:>10} {mc_s:>10} {d_s:>10}")

    # Per-task table
    if show_per_task:
        lines.append("")
        lines.append("PER-TASK DETAIL")
        lines.append("-" * 90)
        header3 = f"{'Task':<30} {'Config':<10} {'Recall':>8} {'MRR':>8} {'MAP':>8} {'Eff':>8} {'OC':>8} {'Steps':>6}"
        lines.append(header3)
        lines.append("-" * 90)
        all_tasks = sorted(per_task_bl + per_task_mcp, key=lambda x: (x["task_id"], x["config"]))
        for t in all_tasks:
            if t.get("skipped"):
                lines.append(f"{t['task_id']:<30} {t['config']:<10} [skipped: {t['skipped']}]")
                continue
            tid = t["task_id"]
            cfg = "BL" if _config_type(t["config"]) == "baseline" else "MCP"
            recall = t.get("file_recall", "—")
            mrr_v = t.get("file_mrr", "—")
            map_v = t.get("file_map", "—")
            eff = t.get("context_efficiency", "—")
            oc = t.get("oracle_coverage", "—")
            steps = t.get("steps_to_first_relevant", "—")
            r_s = f"{recall:.4f}" if isinstance(recall, float) else str(recall)
            m_s = f"{mrr_v:.4f}" if isinstance(mrr_v, float) else str(mrr_v)
            ma_s = f"{map_v:.4f}" if isinstance(map_v, float) else str(map_v)
            e_s = f"{eff:.4f}" if isinstance(eff, float) else str(eff)
            o_s = f"{oc:.4f}" if isinstance(oc, float) else str(oc)
            st_s = str(steps) if steps is not None else "—"
            lines.append(f"{tid:<30} {cfg:<10} {r_s:>8} {m_s:>8} {ma_s:>8} {e_s:>8} {o_s:>8} {st_s:>6}")

    # Comparison per-task
    comp_tasks = comparison.get("per_task", [])
    if comp_tasks:
        lines.append("")
        lines.append("BL vs MCP DELTA (matched tasks)")
        lines.append("-" * 90)
        header4 = f"{'Task':<30} {'Recall Δ':>10} {'MRR Δ':>10} {'MAP Δ':>10} {'Eff Δ':>10} {'OC Δ':>10}"
        lines.append(header4)
        lines.append("-" * 90)
        for ct in sorted(comp_tasks, key=lambda x: x.get("oracle_coverage_delta", 0), reverse=True):
            tid = ct["task_id"]
            r_d = ct.get("file_recall_delta", "—")
            m_d = ct.get("file_mrr_delta", "—")
            ma_d = ct.get("file_map_delta", "—")
            e_d = ct.get("context_efficiency_delta", "—")
            o_d = ct.get("oracle_coverage_delta", "—")
            r_s = f"{r_d:+.4f}" if isinstance(r_d, float) else str(r_d)
            m_s = f"{m_d:+.4f}" if isinstance(m_d, float) else str(m_d)
            ma_s = f"{ma_d:+.4f}" if isinstance(ma_d, float) else str(ma_d)
            e_s = f"{e_d:+.4f}" if isinstance(e_d, float) else str(e_d)
            o_s = f"{o_d:+.4f}" if isinstance(o_d, float) else str(o_d)
            lines.append(f"{tid:<30} {r_s:>10} {m_s:>10} {ma_s:>10} {e_s:>10} {o_s:>10}")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Oracle-based IR analysis for org-scale benchmark tasks."
    )
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--per-task", action="store_true", help="Show per-task detail")
    parser.add_argument("--suite", default="", help="Filter to one suite")
    parser.add_argument(
        "--runs-dir", default=str(STAGING_DIR),
        help=f"Runs directory to scan (default: {STAGING_DIR})",
    )
    parser.add_argument("--output", default=None, help="Write output to file")
    return parser.parse_args()


def main():
    args = parse_args()
    runs_dir = Path(args.runs_dir)

    print(f"Scanning {runs_dir} for org-scale runs...", file=sys.stderr)

    # Discover task runs
    all_runs = walk_org_runs(runs_dir, suite_filter=args.suite)
    print(f"Found {len(all_runs)} task runs", file=sys.stderr)

    # Compute oracle IR for each
    baseline_scores = []
    mcp_scores = []
    skipped = 0

    for run in all_runs:
        task_spec = _find_task_spec(run["task_id"])
        if not task_spec:
            print(f"  SKIP {run['task_id']}: no task_spec.json found", file=sys.stderr)
            skipped += 1
            continue

        scores = compute_oracle_ir(
            task_id=run["task_id"],
            config_name=run["config"],
            task_dir=run["task_dir"],
            transcript_path=run["transcript"],
            task_spec_path=task_spec,
        )
        scores["reward"] = run.get("reward")
        scores["agent_exec_secs"] = run.get("agent_exec_secs")

        if scores.get("skipped"):
            print(f"  SKIP {run['task_id']} ({run['config']}): {scores['skipped']}", file=sys.stderr)
            skipped += 1
            continue

        if run["config_type"] == "baseline":
            baseline_scores.append(scores)
        else:
            mcp_scores.append(scores)

    print(f"Analyzed: {len(baseline_scores)} baseline + {len(mcp_scores)} MCP, {skipped} skipped",
          file=sys.stderr)

    # Aggregate
    bl_agg = aggregate_scores(baseline_scores)
    mcp_agg = aggregate_scores(mcp_scores)
    comparison = compare_configs(baseline_scores, mcp_scores)

    if args.json:
        report = {
            "summary": {
                "n_baseline": len(baseline_scores),
                "n_mcp": len(mcp_scores),
                "n_skipped": skipped,
            },
            "baseline_aggregate": bl_agg,
            "mcp_aggregate": mcp_agg,
            "comparison": comparison,
            "per_task_baseline": baseline_scores if args.per_task else [],
            "per_task_mcp": mcp_scores if args.per_task else [],
        }
        output = json.dumps(report, indent=2, default=str)
    else:
        output = format_report(
            bl_agg, mcp_agg, comparison,
            baseline_scores, mcp_scores,
            show_per_task=args.per_task,
        )

    if args.output:
        Path(args.output).write_text(output)
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
