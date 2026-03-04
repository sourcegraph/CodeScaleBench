#!/usr/bin/env python3
"""Normalize agent traces into step-level retrieval events.

Reads run artifacts (trajectory.json, claude-code.txt, result.json) and writes
one ``{task_name}.retrieval_events.json`` per task-config pair conforming to
``schemas/retrieval_events_schema.json`` (v1.0).

Usage:
    python3 scripts/normalize_retrieval_events.py --run-dir runs/staging/fix_haiku_20260223_140913
    python3 scripts/normalize_retrieval_events.py --run-dir runs/official --all
    python3 scripts/normalize_retrieval_events.py --run-dir runs/staging --all --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Repository root detection
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"
GT_CACHE = REPO_ROOT / "configs" / "ground_truth_files.json"
SELECTION_FILE = REPO_ROOT / "configs" / "selected_benchmark_tasks.json"

sys.path.insert(0, str(SCRIPT_DIR))

from csb_metrics.ground_truth import (
    TaskGroundTruth,
    load_registry,
    build_ground_truth_registry,
    save_registry,
)
from csb_metrics.transcript_paths import resolve_task_transcript_path
from csb_metrics.ir_metrics import _normalize, _looks_like_file

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCHEMA_VERSION = "1.0"

# Skip patterns for run directories
_SKIP_PATTERNS = (
    "archive", "__broken", "__duplicate", "__all_errored",
    "__partial", "__integrated",
)

# Batch timestamp pattern
_BATCH_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}__\d{2}-\d{2}-\d{2}$")

# Tool execution pattern in trajectory.json
_TOOL_EXEC_RE = re.compile(r"Executed (\S+) (toolu_\S+)")

# Regex for "path": "some/file.ext" in JSON-like text
_PATH_JSON_RE = re.compile(r'"path"\s*:\s*"([^"]+)"')


def _normalize_task_name(task_name: str) -> str:
    """Normalize MCP wrapper task names for GT lookup and artifact naming."""
    name = task_name or ""
    if name.startswith("mcp_"):
        name = name[4:]
        name = re.sub(r"_[A-Za-z0-9]{6}$", "", name)
    return name

# ---------------------------------------------------------------------------
# Tool category mapping
# ---------------------------------------------------------------------------
# Maps raw tool names to (category, is_mcp) pairs.

_MCP_TOOL_CATEGORIES: dict[str, str] = {
    # file_read
    "mcp__sourcegraph__sg_read_file": "file_read",
    "mcp__sourcegraph__read_file": "file_read",
    # file_search
    "mcp__sourcegraph__sg_list_files": "file_search",
    "mcp__sourcegraph__list_files": "file_search",
    "mcp__sourcegraph__sg_list_repos": "file_search",
    "mcp__sourcegraph__list_repos": "file_search",
    # symbol_navigation
    "mcp__sourcegraph__sg_find_references": "symbol_navigation",
    "mcp__sourcegraph__find_references": "symbol_navigation",
    "mcp__sourcegraph__sg_go_to_definition": "symbol_navigation",
    "mcp__sourcegraph__go_to_definition": "symbol_navigation",
    # code_search
    "mcp__sourcegraph__sg_keyword_search": "code_search",
    "mcp__sourcegraph__keyword_search": "code_search",
    "mcp__sourcegraph__sg_nls_search": "code_search",
    "mcp__sourcegraph__nls_search": "code_search",
    # commit_search
    "mcp__sourcegraph__sg_commit_search": "commit_search",
    "mcp__sourcegraph__commit_search": "commit_search",
    "mcp__sourcegraph__sg_diff_search": "commit_search",
    "mcp__sourcegraph__diff_search": "commit_search",
    "mcp__sourcegraph__sg_compare_revisions": "commit_search",
    "mcp__sourcegraph__compare_revisions": "commit_search",
    # deep_search
    "mcp__sourcegraph__sg_deepsearch": "deep_search",
    "mcp__sourcegraph__deepsearch": "deep_search",
    "mcp__sourcegraph__sg_deepsearch_read": "deep_search",
    "mcp__sourcegraph__deepsearch_read": "deep_search",
    # other
    "mcp__sourcegraph__sg_get_contributor_repos": "other",
    "mcp__sourcegraph__get_contributor_repos": "other",
}

_LOCAL_TOOL_CATEGORIES: dict[str, str] = {
    "Read": "file_read",
    "Glob": "file_search",
    "Grep": "code_search",
    "Write": "file_write",
    "Edit": "file_write",
    "NotebookEdit": "file_write",
    "Bash": "other",
    "Task": "other",
    "WebFetch": "other",
    "WebSearch": "other",
}

# Tools that are tracked by the retrieval evaluation pipeline.
# Includes retrieval tools plus local write tools for utilization/taxonomy stages.
_TRACKED_TOOLS = (
    set(_MCP_TOOL_CATEGORIES.keys())
    | {"Read", "Glob", "Grep", "Write", "Edit", "NotebookEdit"}
)


def _tool_category(name: str) -> str:
    if name in _MCP_TOOL_CATEGORIES:
        return _MCP_TOOL_CATEGORIES[name]
    if name in _LOCAL_TOOL_CATEGORIES:
        return _LOCAL_TOOL_CATEGORIES[name]
    if name.startswith("mcp__sourcegraph__"):
        return "other"
    return "other"


def _is_mcp(name: str) -> bool:
    return name.startswith("mcp__sourcegraph__")


def _is_retrieval_tool(name: str) -> bool:
    """True for tools tracked by the retrieval evaluation pipeline."""
    if name in _TRACKED_TOOLS:
        return True
    if name.startswith("mcp__sourcegraph__"):
        return True
    return False


# ---------------------------------------------------------------------------
# Ground truth loading
# ---------------------------------------------------------------------------

def _ensure_ground_truth() -> dict[str, TaskGroundTruth]:
    if GT_CACHE.is_file():
        registry = load_registry(GT_CACHE)
        if registry:
            return registry
    selected = _load_selected_tasks()
    registry = build_ground_truth_registry(BENCHMARKS_DIR, selected)
    if registry:
        save_registry(registry, GT_CACHE)
    return registry


def _load_selected_tasks() -> list[dict]:
    if not SELECTION_FILE.is_file():
        return []
    data = json.loads(SELECTION_FILE.read_text())
    return data.get("tasks", [])


# ---------------------------------------------------------------------------
# Transcript event extraction
# ---------------------------------------------------------------------------

def _extract_files_from_tool_input(tool_name: str, tool_input: dict) -> list[str]:
    """Extract file paths from a tool_use input dict."""
    files: list[str] = []
    if not isinstance(tool_input, dict):
        return files

    # Local file tools
    if tool_name in ("Read", "Glob", "Grep", "Write", "Edit", "NotebookEdit"):
        fp = tool_input.get("file_path") or tool_input.get("path") or ""
        if fp and _looks_like_file(_normalize(fp)):
            files.append(fp)
        # Grep/Glob patterns can reference directories
        pattern = tool_input.get("pattern", "")
        if pattern and "/" in pattern and "." in pattern:
            # This is a glob pattern, not a real file
            pass

    # MCP read_file
    elif _is_mcp(tool_name) and "read_file" in tool_name:
        fp = tool_input.get("path", "")
        if fp:
            files.append(fp)

    # MCP find_references / go_to_definition
    elif _is_mcp(tool_name) and any(k in tool_name for k in ("find_references", "go_to_definition")):
        fp = tool_input.get("path", "")
        if fp:
            files.append(fp)

    return files


def _extract_symbols_from_tool_input(tool_name: str, tool_input: dict) -> list[str]:
    """Extract symbol names from symbol_navigation tool calls."""
    if not isinstance(tool_input, dict):
        return []
    if _tool_category(tool_name) != "symbol_navigation":
        return []
    symbol = tool_input.get("symbol", "")
    return [symbol] if symbol else []


def _extract_files_from_tool_result(tool_name: str, content: str) -> list[str]:
    """Extract file paths from a tool_result content string."""
    files: list[str] = []
    if not isinstance(content, str):
        return files

    if _is_mcp(tool_name):
        for m in _PATH_JSON_RE.finditer(content):
            p = m.group(1)
            if _looks_like_file(_normalize(p)):
                files.append(p)
    elif tool_name == "Glob":
        for fline in content.splitlines():
            fline = fline.strip()
            if fline and "/" in fline and "." in fline:
                if _looks_like_file(_normalize(fline)):
                    files.append(fline)
    elif tool_name == "Grep":
        for fline in content.splitlines():
            fline = fline.strip()
            if fline and "/" in fline and "." in fline and not fline.startswith("#"):
                if _looks_like_file(_normalize(fline)):
                    files.append(fline)

    return files


def _salient_arguments(tool_name: str, tool_input: dict) -> dict:
    """Extract salient arguments for recording in the event."""
    if not isinstance(tool_input, dict):
        return {}
    args: dict = {}

    cat = _tool_category(tool_name)
    if cat == "file_read":
        for k in ("file_path", "path", "repo", "startLine", "endLine"):
            if k in tool_input:
                args[k] = tool_input[k]
    elif cat == "file_write":
        for k in ("file_path", "path", "old_string", "new_string", "replace_all"):
            if k in tool_input:
                args[k] = tool_input[k]
    elif cat == "file_search":
        for k in ("pattern", "path", "repo", "query"):
            if k in tool_input:
                args[k] = tool_input[k]
    elif cat == "code_search":
        for k in ("pattern", "query", "path", "repo", "glob", "type"):
            if k in tool_input:
                args[k] = tool_input[k]
    elif cat == "symbol_navigation":
        for k in ("symbol", "path", "repo"):
            if k in tool_input:
                args[k] = tool_input[k]
    elif cat == "commit_search":
        for k in ("pattern", "repo", "repos", "messageTerms", "contentTerms",
                   "authors", "base", "head"):
            if k in tool_input:
                args[k] = tool_input[k]
    elif cat == "deep_search":
        for k in ("question", "identifier"):
            if k in tool_input:
                args[k] = tool_input[k]

    return args


def _extract_events_from_transcript(transcript_path: Path) -> list[dict]:
    """Parse claude-code.txt JSONL and produce step-level retrieval events."""
    if not transcript_path.is_file():
        return []

    events: list[dict] = []
    step_index = 0
    # Map tool_use_id -> (tool_name, tool_input, step_index)
    tool_id_map: dict[str, tuple[str, dict, int]] = {}

    # First pass: extract tool_use blocks
    tool_use_entries: list[tuple[str, str, dict]] = []  # (tool_use_id, name, input)

    lines = transcript_path.read_text(errors="replace").splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = entry.get("type", "")

        if msg_type == "assistant":
            message = entry.get("message", entry)
            content_blocks = message.get("content", [])
            if not isinstance(content_blocks, list):
                continue
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = block.get("name", "")
                    tid = block.get("id", "")
                    inp = block.get("input", {})
                    if isinstance(inp, str):
                        try:
                            inp = json.loads(inp)
                        except json.JSONDecodeError:
                            inp = {}

                    if not _is_retrieval_tool(name):
                        step_index += 1
                        if tid and name:
                            tool_id_map[tid] = (name, inp if isinstance(inp, dict) else {}, step_index - 1)
                        continue

                    target_files = _extract_files_from_tool_input(name, inp)
                    target_symbols = _extract_symbols_from_tool_input(name, inp)

                    event = {
                        "step_index": step_index,
                        "timestamp": None,  # Transcript doesn't always have per-step timestamps
                        "tool_name": name,
                        "tool_category": _tool_category(name),
                        "is_mcp": _is_mcp(name),
                        "arguments": _salient_arguments(name, inp if isinstance(inp, dict) else {}),
                        "target_files": [_normalize(f) for f in target_files],
                        "target_symbols": target_symbols,
                        "hits_ground_truth": False,
                        "matched_ground_truth_files": [],
                        "is_subagent": False,
                        "cumulative_tokens": None,
                        "elapsed_seconds": None,
                    }
                    events.append(event)

                    if tid and name:
                        tool_id_map[tid] = (name, inp if isinstance(inp, dict) else {}, step_index)

                    step_index += 1

        elif msg_type == "user":
            message = entry.get("message", entry)
            content_blocks = message.get("content", [])
            if not isinstance(content_blocks, list):
                continue
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tid = block.get("tool_use_id", "")
                    if tid not in tool_id_map:
                        continue
                    tname, _, eidx = tool_id_map[tid]
                    if not _is_retrieval_tool(tname):
                        continue

                    raw = block.get("content", "")
                    if isinstance(raw, list):
                        raw = " ".join(
                            item.get("text", "") if isinstance(item, dict) else str(item)
                            for item in raw
                        )
                    if not isinstance(raw, str):
                        raw = str(raw)

                    result_files = _extract_files_from_tool_result(tname, raw)
                    # Find the matching event and merge result files
                    for evt in events:
                        if evt["step_index"] == eidx:
                            norm_result = [_normalize(f) for f in result_files]
                            existing = set(evt["target_files"])
                            for nf in norm_result:
                                if nf not in existing:
                                    evt["target_files"].append(nf)
                                    existing.add(nf)
                            break

    return events


def _extract_events_from_trajectory(trajectory_path: Path) -> list[dict]:
    """Parse trajectory.json and produce step-level retrieval events."""
    if not trajectory_path.is_file():
        return []

    try:
        traj = json.loads(trajectory_path.read_text(errors="replace"))
    except (json.JSONDecodeError, OSError):
        return []

    steps = traj.get("steps", [])
    if not steps:
        return []

    events: list[dict] = []
    step_index = 0

    # Find session start time
    start_ts = _parse_ts(steps[0].get("timestamp", ""))

    for step in steps:
        tool_calls = step.get("tool_calls", [])
        if not tool_calls:
            continue

        ts_str = step.get("timestamp")
        ts_epoch = _parse_ts(ts_str) if ts_str else None
        elapsed = round(ts_epoch - start_ts, 1) if (ts_epoch is not None and start_ts is not None) else None

        # Token metrics
        metrics = step.get("metrics", {})
        cum_tokens = None
        if metrics:
            prompt = metrics.get("prompt_tokens", 0) or 0
            completion = metrics.get("completion_tokens", 0) or 0
            cached = metrics.get("cached_tokens", 0) or 0
            cum_tokens = prompt + completion + cached

        for tc in tool_calls:
            name = tc.get("function_name", "") or tc.get("name", "")
            if not name:
                continue

            if not _is_retrieval_tool(name):
                step_index += 1
                continue

            args = tc.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}

            target_files = [_normalize(f) for f in _extract_files_from_tool_input(name, args)]
            target_symbols = _extract_symbols_from_tool_input(name, args)

            # Check observation for result files
            obs = step.get("observation", {})
            if isinstance(obs, dict):
                obs_content = obs.get("content", "")
                if isinstance(obs_content, str):
                    result_files = [_normalize(f) for f in _extract_files_from_tool_result(name, obs_content)]
                    existing = set(target_files)
                    for rf in result_files:
                        if rf not in existing:
                            target_files.append(rf)
                            existing.add(rf)

            event = {
                "step_index": step_index,
                "timestamp": ts_str,
                "tool_name": name,
                "tool_category": _tool_category(name),
                "is_mcp": _is_mcp(name),
                "arguments": _salient_arguments(name, args),
                "target_files": target_files,
                "target_symbols": target_symbols,
                "hits_ground_truth": False,
                "matched_ground_truth_files": [],
                "is_subagent": False,
                "cumulative_tokens": cum_tokens,
                "elapsed_seconds": elapsed,
            }
            events.append(event)
            step_index += 1

    return events


def _parse_ts(s: str | None) -> float | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Ground truth matching
# ---------------------------------------------------------------------------

def _annotate_ground_truth(
    events: list[dict],
    gt_files: list[str],
) -> None:
    """Annotate events with ground truth hits (in-place)."""
    gt_normalized = {_normalize(f) for f in gt_files}
    if not gt_normalized:
        return

    for evt in events:
        matched = []
        for tf in evt["target_files"]:
            norm_tf = _normalize(tf)
            if norm_tf in gt_normalized:
                matched.append(norm_tf)
        evt["matched_ground_truth_files"] = matched
        evt["hits_ground_truth"] = len(matched) > 0


def _infer_expected_edit_files(
    gt: TaskGroundTruth | None,
) -> tuple[list[str], str | None, str | None]:
    """Conservatively infer expected edit-target files from ground-truth provenance.

    `TaskGroundTruth.files` is often a relevant-file set, not strictly an edit-target set.
    We only expose `expected_edit_files` when the source strongly implies edit targets.
    """
    if not gt or not gt.files:
        return ([], None, None)

    source = (gt.source or "").strip()

    # High-confidence edit-target sources.
    if source == "expected_changes_json":
        return (list(gt.files), "expected_changes_json", "high")
    if source == "patch":
        return (list(gt.files), "patch", "high")

    # Some ground_truth.json schemas use a "buggy" file field, which is usually
    # a true edit target for fix-style tasks.
    if source == "ground_truth_json_buggy":
        return (list(gt.files), "ground_truth_json_buggy", gt.confidence or "high")

    # Otherwise, treat files as relevant evidence only.
    return ([], None, None)


# ---------------------------------------------------------------------------
# Event summary
# ---------------------------------------------------------------------------

def _compute_summary(events: list[dict], gt_files: list[str]) -> dict:
    gt_normalized = {_normalize(f) for f in gt_files}
    all_files: set[str] = set()
    gt_hit: set[str] = set()
    by_category: dict[str, int] = {}
    mcp_count = 0
    local_count = 0
    first_gt_step: int | None = None

    for evt in events:
        cat = evt["tool_category"]
        by_category[cat] = by_category.get(cat, 0) + 1
        if evt["is_mcp"]:
            mcp_count += 1
        else:
            local_count += 1
        for tf in evt["target_files"]:
            all_files.add(_normalize(tf))
        for mf in evt["matched_ground_truth_files"]:
            gt_hit.add(_normalize(mf))
            if first_gt_step is None:
                first_gt_step = evt["step_index"]

    return {
        "total_events": len(events),
        "mcp_events": mcp_count,
        "local_events": local_count,
        "unique_files_accessed": len(all_files),
        "ground_truth_files_hit": len(gt_hit),
        "ground_truth_files_total": len(gt_normalized),
        "first_ground_truth_hit_step": first_gt_step,
        "events_by_category": by_category,
    }


# ---------------------------------------------------------------------------
# Run directory walking
# ---------------------------------------------------------------------------

def _extract_task_id(dir_name: str) -> str:
    parts = dir_name.split("__")
    if len(parts) >= 2:
        return "__".join(parts[:-1])
    return dir_name


def _infer_benchmark(run_name: str) -> str:
    """Infer benchmark suite from run directory name."""
    name = run_name.lower()
    # SDLC phases
    for phase in ("build", "debug", "design", "document", "fix", "secure", "test", "understand"):
        if name.startswith(phase + "_"):
            return f"ccb_{phase}"
    # MCP-unique suites
    for suite in ("mcp_crossorg", "mcp_compliance", "mcp_incident", "mcp_migration",
                   "mcp_onboarding", "mcp_crossrepo_tracing", "mcp_platform", "mcp_security"):
        if suite.replace("_", "") in name.replace("_", ""):
            return f"ccb_{suite}"
    # Other known prefixes
    for prefix, bench in [
        ("swebench", "ccb_swebenchpro"), ("locobench", "ccb_locobench"),
        ("pytorch", "ccb_pytorch"), ("tac", "ccb_tac"),
    ]:
        if name.startswith(prefix):
            return bench
    return "unknown"


def walk_run_tasks(run_dir: Path) -> list[dict]:
    """Walk a single run directory and yield task info dicts."""
    tasks: list[dict] = []

    for config_dir in sorted(run_dir.iterdir()):
        if not config_dir.is_dir():
            continue
        config_name = config_dir.name
        # Skip non-config directories
        if not (config_name == "mcp" or any(config_name.startswith(p) for p in ("baseline", "mcp-", "sourcegraph"))):
            continue

        for batch_dir in sorted(config_dir.iterdir()):
            if not batch_dir.is_dir():
                continue
            is_batch_ts = bool(_BATCH_TS_RE.match(batch_dir.name))
            is_job_dir = batch_dir.name.startswith(("ccb_", "csb_"))

            if not is_batch_ts and not is_job_dir:
                continue

            for task_dir in sorted(batch_dir.iterdir()):
                if not task_dir.is_dir() or "__" not in task_dir.name:
                    continue

                result_file = task_dir / "result.json"
                if not result_file.is_file():
                    continue

                task_name = _extract_task_id(task_dir.name)
                try:
                    rdata = json.loads(result_file.read_text())
                    if "task_name" in rdata:
                        task_name = rdata["task_name"]
                except (json.JSONDecodeError, OSError):
                    rdata = {}
                task_name = _normalize_task_name(task_name)

                tasks.append({
                    "task_name": task_name,
                    "config_name": config_name,
                    "task_dir": task_dir,
                    "batch_timestamp": batch_dir.name if is_batch_ts else "",
                    "result_data": rdata,
                })

    return tasks


def walk_all_runs(runs_root: Path) -> list[dict]:
    """Walk a runs/staging/ or runs/official/ root and yield task info dicts."""
    all_tasks: list[dict] = []

    for run_dir in sorted(runs_root.iterdir()):
        if not run_dir.is_dir() or run_dir.name in ("archive", "MANIFEST.json"):
            continue
        if any(pat in run_dir.name for pat in _SKIP_PATTERNS):
            continue

        for info in walk_run_tasks(run_dir):
            info["run_id"] = run_dir.name
            info["benchmark"] = _infer_benchmark(run_dir.name)
            all_tasks.append(info)

    return all_tasks


# ---------------------------------------------------------------------------
# Normalization pipeline
# ---------------------------------------------------------------------------

def normalize_task(
    info: dict,
    gt_registry: dict[str, TaskGroundTruth],
) -> dict:
    """Produce a normalized retrieval events document for one task."""
    task_dir: Path = info["task_dir"]
    task_name: str = _normalize_task_name(info["task_name"])
    config_name: str = info["config_name"]
    run_id: str = info.get("run_id", task_dir.parent.parent.parent.name)
    benchmark: str = info.get("benchmark", "unknown")
    rdata: dict = info.get("result_data", {})

    # Model
    model = None
    agent_info = rdata.get("agent_info", {})
    if isinstance(agent_info, dict):
        mi = agent_info.get("model_info", {})
        if isinstance(mi, dict):
            model = mi.get("name")

    # Resolve trace files
    transcript_path = resolve_task_transcript_path(task_dir)
    trajectory_path = task_dir / "agent" / "trajectory.json"

    has_transcript = transcript_path.is_file()
    has_trajectory = trajectory_path.is_file()

    # Extract events — prefer trajectory, merge with transcript
    events: list[dict] = []
    trace_source: str | None = None

    if has_trajectory:
        events = _extract_events_from_trajectory(trajectory_path)
        trace_source = "trajectory"

    if has_transcript and not events:
        events = _extract_events_from_transcript(transcript_path)
        trace_source = "transcript"
    elif has_transcript and events:
        # Trajectory had events; still check transcript for additional files
        # from tool results that trajectory might not capture
        transcript_events = _extract_events_from_transcript(transcript_path)
        if transcript_events:
            # Merge: use trajectory events as base, enrich target_files from transcript
            traj_steps = {e["step_index"]: e for e in events}
            for te in transcript_events:
                if te["step_index"] in traj_steps:
                    existing = set(traj_steps[te["step_index"]]["target_files"])
                    for tf in te["target_files"]:
                        if tf not in existing:
                            traj_steps[te["step_index"]]["target_files"].append(tf)
                            existing.add(tf)
            trace_source = "merged"

    degraded_reason: str | None = None
    if not has_trajectory and not has_transcript:
        degraded_reason = "No trajectory.json or claude-code.txt found"
        trace_source = None
    elif not events:
        degraded_reason = "Trace files exist but no retrieval events could be extracted"

    # Ground truth
    gt = gt_registry.get(task_name)
    gt_files: list[str] = gt.files if gt else []
    gt_source: str | None = gt.source if gt else None
    gt_confidence: str | None = gt.confidence if gt else None
    has_ground_truth = bool(gt_files)

    # Chunk-level ground truth (from defect annotations)
    gt_chunks: list[dict] = []
    has_chunk_gt = False
    if gt and gt.defect_annotations:
        has_chunk_gt = True
        for ann in gt.defect_annotations:
            chunk: dict = {"file": ann.file}
            if ann.line_start is not None:
                chunk["line_start"] = ann.line_start
            else:
                chunk["line_start"] = 1
            if ann.line_end is not None:
                chunk["line_end"] = ann.line_end
            else:
                chunk["line_end"] = chunk["line_start"]
            chunk["annotation"] = ann.defect_type
            gt_chunks.append(chunk)

    # Annotate events with ground truth
    _annotate_ground_truth(events, gt_files)

    # Build document
    now = datetime.now(timezone.utc).isoformat()

    expected_edit_files, expected_edit_source, expected_edit_conf = _infer_expected_edit_files(gt)

    ground_truth_section: dict = {"files": gt_files}
    if gt_chunks:
        ground_truth_section["chunks"] = gt_chunks
    if expected_edit_files:
        ground_truth_section["expected_edit_files"] = expected_edit_files
        ground_truth_section["expected_edit_files_source"] = expected_edit_source
        ground_truth_section["expected_edit_files_confidence"] = expected_edit_conf

    doc = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now,
        "provenance": {
            "run_id": run_id,
            "batch_timestamp": info.get("batch_timestamp"),
            "task_name": task_name,
            "trial_name": task_dir.name,
            "config_name": config_name,
            "benchmark": benchmark,
            "model": model,
        },
        "coverage": {
            "has_trajectory": has_trajectory,
            "has_transcript": has_transcript,
            "has_ground_truth": has_ground_truth,
            "has_chunk_ground_truth": has_chunk_gt,
            "trace_source": trace_source,
            "degraded_reason": degraded_reason,
            "ground_truth_source": gt_source,
            "ground_truth_confidence": gt_confidence,
        },
        "ground_truth": ground_truth_section,
        "events": events,
        "summary": _compute_summary(events, gt_files),
    }

    return doc


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------

def _output_path_for_task(run_dir: Path, config_name: str, task_name: str) -> Path:
    """Compute output path: {run_dir}/retrieval_events/{config}/{task}.retrieval_events.json"""
    return run_dir / "retrieval_events" / config_name / f"{task_name}.retrieval_events.json"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize agent traces into step-level retrieval events.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 scripts/normalize_retrieval_events.py --run-dir runs/staging/fix_haiku_20260223\n"
            "  python3 scripts/normalize_retrieval_events.py --run-dir runs/staging --all\n"
            "  python3 scripts/normalize_retrieval_events.py --run-dir runs/staging --all --dry-run\n"
        ),
    )
    parser.add_argument(
        "--run-dir", required=True, type=Path,
        help="Path to a single run directory, or parent (runs/staging/) when --all is set.",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Walk all runs under --run-dir (instead of treating it as a single run).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be written without writing files.",
    )
    parser.add_argument(
        "--task", type=str, default=None,
        help="Normalize only this task (by task_name). Useful for debugging.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Print JSON summary to stdout.",
    )
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()
    if not run_dir.is_dir():
        print(f"Error: {run_dir} is not a directory", file=sys.stderr)
        sys.exit(1)

    # Load ground truth
    gt_registry = _ensure_ground_truth()

    # Discover tasks
    if args.all:
        task_infos = walk_all_runs(run_dir)
    else:
        task_infos = walk_run_tasks(run_dir)
        for info in task_infos:
            info["run_id"] = run_dir.name
            info["benchmark"] = _infer_benchmark(run_dir.name)

    if args.task:
        task_infos = [t for t in task_infos if t["task_name"] == args.task]

    if not task_infos:
        print("No tasks found.", file=sys.stderr)
        sys.exit(0)

    # Sort for deterministic output ordering
    task_infos.sort(key=lambda t: (
        t.get("run_id", ""),
        t.get("config_name", ""),
        t.get("task_name", ""),
        t.get("batch_timestamp", ""),
    ))

    written = 0
    skipped = 0
    degraded = 0
    summary_records: list[dict] = []

    for info in task_infos:
        doc = normalize_task(info, gt_registry)

        # Determine output path
        run_parent = info["task_dir"].parent.parent.parent  # batch -> config -> run
        if args.all:
            # run_parent is the run dir itself
            out_path = _output_path_for_task(run_parent, info["config_name"], info["task_name"])
        else:
            out_path = _output_path_for_task(run_dir, info["config_name"], info["task_name"])

        if doc["coverage"]["degraded_reason"]:
            degraded += 1

        if args.dry_run:
            print(f"[dry-run] Would write: {out_path}")
            print(f"  events={len(doc['events'])} coverage={doc['coverage']['trace_source']} gt={len(doc['ground_truth']['files'])}")
        else:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(doc, indent=2) + "\n")
            written += 1

        summary_records.append({
            "task_name": info["task_name"],
            "config_name": info["config_name"],
            "events": len(doc["events"]),
            "trace_source": doc["coverage"]["trace_source"],
            "gt_files": len(doc["ground_truth"]["files"]),
            "gt_hit": doc["summary"]["ground_truth_files_hit"],
            "degraded": doc["coverage"]["degraded_reason"] is not None,
        })

    # Summary
    print(f"\nNormalized {len(task_infos)} tasks: {written} written, {degraded} degraded")

    if args.json:
        print(json.dumps({
            "total": len(task_infos),
            "written": written,
            "degraded": degraded,
            "tasks": summary_records,
        }, indent=2))


if __name__ == "__main__":
    main()
