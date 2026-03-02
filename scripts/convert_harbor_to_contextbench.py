#!/usr/bin/env python3
"""Convert Harbor ATIF traces to ContextBench trajectory format.

Reads Harbor run artifacts (claude-code.txt JSONL transcripts) and converts
them to ContextBench's expected trajectory format for evaluation.

ContextBench expects:
  {
    "instance_id": "owner__repo-1234",
    "traj_data": {
      "pred_steps": [{"files": [...], "spans": {...}, "symbols": {...}}, ...],
      "pred_files": [...],
      "pred_spans": {"file": [{"start": N, "end": M}]},
      "pred_symbols": {"file": ["symbol_name"]}
    },
    "model_patch": "unified diff..."
  }

Our Harbor traces have claude-code.txt JSONL with tool_use blocks containing
Read, Grep, Glob, Edit, Write (baseline) and mcp__sourcegraph__* (MCP) calls.

Usage:
    python3 scripts/convert_harbor_to_contextbench.py \\
        --run-dir runs/staging/ccb_contextbench_haiku_* \\
        --output results/contextbench_pilot/

    python3 scripts/convert_harbor_to_contextbench.py \\
        --run-dir runs/staging/ccb_contextbench_haiku_20260310 \\
        --selection configs/contextbench_pilot_50.json \\
        --output results/contextbench_pilot/
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from normalize_retrieval_events import (
    _extract_files_from_tool_input,
    _extract_files_from_tool_result,
    _extract_symbols_from_tool_input,
    _is_mcp,
    _is_retrieval_tool,
    _tool_category,
)

log = logging.getLogger(__name__)

# Regex for "file": "some/path.ext" in MCP keyword_search results
# (complements _PATH_JSON_RE in normalize_retrieval_events which matches "path")
_FILE_JSON_RE = re.compile(r'"file"\s*:\s*"([^"]+)"')


def _extract_files_from_mcp_result(content: str) -> list[str]:
    """Extract file paths from MCP tool results.

    Supplements _extract_files_from_tool_result by also matching "file" keys
    used by Sourcegraph keyword_search (which returns {"blocks":[{"file":"..."}]}).
    """
    files = []
    for m in _FILE_JSON_RE.finditer(content):
        p = m.group(1)
        # Filter out non-file values (e.g., "file": "line")
        if "/" in p and "." in p.split("/")[-1]:
            files.append(p)
    return files

# Prefixes to strip from file paths to get repo-relative paths
_WORKSPACE_PREFIXES = (
    "/workspace/",
    "/app/",
    "/testbed/",
    "/repo_full/",
    "/tmp/agent_work/",
)

# Batch timestamp pattern
_BATCH_TS_RE = re.compile(r"\d{4}-\d{2}-\d{2}__\d{2}-\d{2}-\d{2}$")

# Config directory names
_BASELINE_CONFIGS = ("baseline", "baseline-local-direct", "baseline-local-artifact")
_MCP_CONFIGS = ("mcp", "mcp-remote-direct", "mcp-remote-artifact")


def _normalize_path(path: str) -> str:
    """Normalize file path to repo-relative by stripping workspace prefixes."""
    for prefix in _WORKSPACE_PREFIXES:
        if path.startswith(prefix):
            path = path[len(prefix):]
            break
    # Also strip leading /
    path = path.lstrip("/")
    # Strip sg-evals mirror repo prefix if present (e.g., "django--abc123/src/...")
    # MCP tools return paths relative to repo root already
    return path


def _extract_spans_from_read(tool_input: dict) -> dict[str, list[dict]]:
    """Extract line-range spans from a Read tool call.

    Returns {file_path: [{start: N, end: M}]} if offset/limit present.
    """
    file_path = tool_input.get("file_path") or tool_input.get("path") or ""
    if not file_path:
        return {}

    file_path = _normalize_path(file_path)
    offset = tool_input.get("offset")
    limit = tool_input.get("limit")

    if offset is not None and limit is not None:
        try:
            start = int(offset)
            end = start + int(limit)
            return {file_path: [{"start": max(1, start), "end": end}]}
        except (ValueError, TypeError):
            pass

    # No specific range — record presence but no span
    return {}


def _extract_spans_from_mcp_read(tool_input: dict) -> dict[str, list[dict]]:
    """Extract line-range spans from an MCP read_file call."""
    file_path = tool_input.get("path", "")
    if not file_path:
        return {}

    file_path = _normalize_path(file_path)
    start_line = tool_input.get("startLine") or tool_input.get("start_line")
    end_line = tool_input.get("endLine") or tool_input.get("end_line")

    if start_line is not None and end_line is not None:
        try:
            return {file_path: [{"start": int(start_line), "end": int(end_line)}]}
        except (ValueError, TypeError):
            pass

    return {}


def _parse_transcript_to_steps(
    transcript_path: Path,
) -> list[dict[str, Any]]:
    """Parse claude-code.txt JSONL into ContextBench pred_steps.

    Each retrieval tool call becomes one step with:
      files: [str]
      spans: {file: [{start, end}]}
      symbols: {file: [symbol_name]}
    """
    if not transcript_path.is_file():
        return []

    steps: list[dict] = []
    # Map tool_use_id -> (tool_name, tool_input, step_idx)
    pending_tools: dict[str, tuple[str, dict, int]] = {}

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
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue

                name = block.get("name", "")
                tid = block.get("id", "")
                inp = block.get("input", {})
                if isinstance(inp, str):
                    try:
                        inp = json.loads(inp)
                    except json.JSONDecodeError:
                        inp = {}
                if not isinstance(inp, dict):
                    inp = {}

                # Only process retrieval + write tools
                cat = _tool_category(name)
                if cat == "other":
                    continue

                files_from_input = [
                    _normalize_path(f) for f in _extract_files_from_tool_input(name, inp)
                ]
                symbols = _extract_symbols_from_tool_input(name, inp)

                # Extract spans
                spans: dict[str, list[dict]] = {}
                if name == "Read" or (name == "read_file"):
                    spans = _extract_spans_from_read(inp)
                elif _is_mcp(name) and "read_file" in name:
                    spans = _extract_spans_from_mcp_read(inp)

                step_idx = len(steps)
                step = {
                    "files": list(set(files_from_input)),
                    "spans": spans,
                    "symbols": {},
                    "_tool_name": name,
                    "_is_mcp": _is_mcp(name),
                    "_category": cat,
                }

                # Add symbols keyed by file
                if symbols and files_from_input:
                    for f in files_from_input:
                        step["symbols"][f] = symbols

                steps.append(step)
                if tid:
                    pending_tools[tid] = (name, inp, step_idx)

        elif msg_type == "user":
            message = entry.get("message", entry)
            content_blocks = message.get("content", [])
            if not isinstance(content_blocks, list):
                continue

            for block in content_blocks:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue

                tid = block.get("tool_use_id", "")
                if tid not in pending_tools:
                    continue

                tname, _, step_idx = pending_tools[tid]

                raw = block.get("content", "")
                if isinstance(raw, list):
                    raw = " ".join(
                        item.get("text", "") if isinstance(item, dict) else str(item)
                        for item in raw
                    )
                if not isinstance(raw, str):
                    raw = str(raw)

                result_files = [
                    _normalize_path(f) for f in _extract_files_from_tool_result(tname, raw)
                ]
                # Also extract "file" keys from MCP results (keyword_search uses this)
                if _is_mcp(tname):
                    extra_files = [
                        _normalize_path(f) for f in _extract_files_from_mcp_result(raw)
                    ]
                    result_files.extend(extra_files)

                # Extract spans from structured MCP results (keyword_search chunks)
                result_spans: dict[str, list[dict]] = {}
                if _is_mcp(tname) and raw:
                    try:
                        result_json = json.loads(raw)
                        for block in result_json.get("blocks", []):
                            bf = block.get("file", "")
                            if bf:
                                bf = _normalize_path(bf)
                                for chunk in block.get("chunks", []):
                                    sl = chunk.get("startLine")
                                    el = chunk.get("endLine")
                                    if sl is not None and el is not None:
                                        if bf not in result_spans:
                                            result_spans[bf] = []
                                        result_spans[bf].append(
                                            {"start": int(sl), "end": int(el)}
                                        )
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        pass

                if step_idx < len(steps) and (result_files or result_spans):
                    existing = set(steps[step_idx]["files"])
                    for f in result_files:
                        if f not in existing:
                            steps[step_idx]["files"].append(f)
                            existing.add(f)
                    # Merge result spans into step spans
                    for f, spans_list in result_spans.items():
                        if f not in steps[step_idx]["spans"]:
                            steps[step_idx]["spans"][f] = []
                        steps[step_idx]["spans"][f].extend(spans_list)

    return steps


def _extract_model_patch(run_task_dir: Path) -> str:
    """Extract the agent's git diff from verifier output or workspace."""
    diff_path = run_task_dir / "verifier" / "agent.diff"
    if not diff_path.exists():
        diff_path = run_task_dir / "logs" / "verifier" / "agent.diff"
    if diff_path.exists():
        return diff_path.read_text(errors="replace")
    return ""


def convert_task_trace(
    instance_id: str,
    transcript_path: Path,
    run_task_dir: Path,
) -> dict | None:
    """Convert a single task's trace to ContextBench trajectory format."""
    steps = _parse_transcript_to_steps(transcript_path)

    if not steps:
        log.warning("No retrieval steps found for %s", instance_id)
        # Still produce an entry with empty predictions
        return {
            "instance_id": instance_id,
            "traj_data": {
                "pred_steps": [],
                "pred_files": [],
                "pred_spans": {},
                "pred_symbols": {},
            },
            "model_patch": _extract_model_patch(run_task_dir),
        }

    # Build aggregated pred_files, pred_spans, pred_symbols
    all_files: list[str] = []
    all_spans: dict[str, list[dict]] = {}
    all_symbols: dict[str, list[str]] = {}
    seen_files: set[str] = set()

    # Clean steps for output (remove internal fields)
    clean_steps = []
    for step in steps:
        clean_step = {
            "files": step["files"],
            "spans": step["spans"],
            "symbols": step["symbols"],
        }
        clean_steps.append(clean_step)

        for f in step["files"]:
            if f not in seen_files:
                all_files.append(f)
                seen_files.add(f)

        for f, spans in step["spans"].items():
            if f not in all_spans:
                all_spans[f] = []
            all_spans[f].extend(spans)

        for f, syms in step["symbols"].items():
            if f not in all_symbols:
                all_symbols[f] = []
            for s in syms:
                if s not in all_symbols[f]:
                    all_symbols[f].append(s)

    return {
        "instance_id": instance_id,
        "traj_data": {
            "pred_steps": clean_steps,
            "pred_files": all_files,
            "pred_spans": all_spans,
            "pred_symbols": all_symbols,
        },
        "model_patch": _extract_model_patch(run_task_dir),
    }


def _extract_task_id_from_job_log(
    batch_dir: Path,
    known_task_ids: list[str] | None = None,
) -> str | None:
    """Extract full task ID from job.log by matching against known task IDs.

    Falls back to regex extraction if no known IDs provided.
    """
    job_log = batch_dir / "job.log"
    if not job_log.exists():
        return None
    try:
        text = job_log.read_text(errors="replace")
    except OSError:
        return None

    # Primary: match against known task IDs from selection file
    if known_task_ids:
        for tid in known_task_ids:
            if tid in text:
                return tid

    # Fallback: regex for baseline paths (reliable, no truncation)
    m = re.search(r"benchmarks/ccb_contextbench/(cb-[^/]+)/environment", text)
    if m:
        return m.group(1)

    return None


def _find_task_dirs(
    run_dir: Path,
    config_name: str,
    known_task_ids: list[str] | None = None,
) -> list[tuple[str, Path, Path]]:
    """Find task transcript paths under a run directory for a given config.

    Returns list of (task_name, transcript_path, task_dir).
    task_name is the full task ID extracted from job.log when possible.
    """
    results = []
    config_dir = run_dir / config_name
    if not config_dir.is_dir():
        return results

    # Harbor nested format: config/timestamp/task_dir/agent/claude-code.txt
    for batch_dir in config_dir.iterdir():
        if not batch_dir.is_dir():
            continue
        if not _BATCH_TS_RE.search(batch_dir.name):
            continue

        # Try to get full task ID from job.log (avoids truncation)
        full_task_id = _extract_task_id_from_job_log(batch_dir, known_task_ids)

        for task_dir in batch_dir.iterdir():
            if not task_dir.is_dir():
                continue
            transcript = task_dir / "agent" / "claude-code.txt"
            if transcript.exists():
                task_name = full_task_id if full_task_id else task_dir.name
                results.append((task_name, transcript, task_dir))

    # Old promoted format: config/task_dir/agent/claude-code.txt
    if not results:
        for task_dir in config_dir.iterdir():
            if not task_dir.is_dir():
                continue
            transcript = task_dir / "agent" / "claude-code.txt"
            if transcript.exists():
                results.append((task_dir.name, transcript, task_dir))

    return results


def _task_name_to_instance_id(
    task_name: str,
    selection: dict | None = None,
) -> str | None:
    """Map Harbor task name back to ContextBench instance_id.

    Harbor task names look like: cb-django__django-14434_abc123__XyZpQr
    ContextBench instance_ids look like: django__django-14434

    When full task IDs are extracted from job.log, they look like:
      cb-swe-polybench__typescript__maintenance__bugfix__708894b2
    which match task_id in the selection file directly.

    Also handles mcp_ and bl_ prefixes.
    """
    # Try matching the raw task name against selection BEFORE stripping.
    # Full task IDs from job.log match task_id directly.
    if selection:
        for task in selection.get("tasks", []):
            iid = task.get("instance_id", "")
            tid = task.get("task_id", "")
            if task_name == tid or task_name == iid:
                return iid
            if task_name.lower() == tid.lower() or task_name.lower() == iid.lower():
                return iid

    # Fall back to stripping for truncated directory names
    name = task_name
    # Strip Harbor random suffix: __[A-Za-z0-9]{6,8}
    name = re.sub(r"__[A-Za-z0-9]{5,8}$", "", name)
    # Strip mcp_/bl_/sgonly_ prefix
    for prefix in ("mcp_", "bl_", "sgonly_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    # Strip cb- prefix (our scaffolding prefix)
    if name.startswith("cb-"):
        name = name[3:]

    # Try direct match against selection file
    if selection:
        for task in selection.get("tasks", []):
            iid = task.get("instance_id", "")
            tid = task.get("task_id", "")
            if name == iid or name == tid or f"cb-{name}" == tid:
                return iid

        # Harbor truncates task directory names, so try case-insensitive
        # prefix matching — only if unambiguous
        name_lower = name.lower()
        candidates = []
        for task in selection.get("tasks", []):
            iid = task.get("instance_id", "")
            tid = task.get("task_id", "")
            tid_clean = tid[3:] if tid.startswith("cb-") else tid
            if tid_clean.lower().startswith(name_lower) or iid.lower().startswith(name_lower):
                candidates.append(iid)
        if len(candidates) == 1:
            return candidates[0]
        elif candidates:
            log.warning("Ambiguous prefix match for %r: %d candidates", name, len(candidates))

    # If no selection, return the cleaned name (may need manual mapping)
    return name if name else None


def convert_run(
    run_dir: Path,
    output_dir: Path,
    selection_file: Path | None = None,
) -> dict[str, int]:
    """Convert all traces in a run directory.

    Returns stats dict with counts.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    selection = None
    if selection_file and selection_file.exists():
        selection = json.loads(selection_file.read_text())

    stats = {"baseline": 0, "mcp": 0, "skipped": 0, "no_match": 0}

    # Build list of known task IDs for job.log matching
    known_task_ids = None
    if selection:
        known_task_ids = [t["task_id"] for t in selection.get("tasks", []) if "task_id" in t]

    for config_label, config_names in [
        ("baseline", _BASELINE_CONFIGS),
        ("mcp", _MCP_CONFIGS),
    ]:
        trajectories = []

        for config_name in config_names:
            task_dirs = _find_task_dirs(run_dir, config_name, known_task_ids)
            if task_dirs:
                log.info("Found %d tasks in %s/%s", len(task_dirs), run_dir.name, config_name)

            for task_name, transcript_path, task_dir in task_dirs:
                instance_id = _task_name_to_instance_id(task_name, selection)
                if not instance_id:
                    log.warning("Could not map task name to instance_id: %s", task_name)
                    stats["no_match"] += 1
                    continue

                traj = convert_task_trace(instance_id, transcript_path, task_dir)
                if traj:
                    trajectories.append(traj)
                    stats[config_label] += 1

                    # Also write individual trajectory
                    per_task_path = output_dir / config_label / f"{instance_id}.traj.json"
                    per_task_path.parent.mkdir(parents=True, exist_ok=True)
                    per_task_path.write_text(json.dumps(traj, indent=2) + "\n")

        # Write combined JSONL (one JSON per line)
        if trajectories:
            combined_path = output_dir / f"{config_label}_trajectories.traj.json"
            with open(combined_path, "w") as f:
                for traj in trajectories:
                    f.write(json.dumps(traj) + "\n")
            log.info("Wrote %d %s trajectories to %s", len(trajectories), config_label, combined_path)

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Convert Harbor traces to ContextBench trajectory format"
    )
    parser.add_argument(
        "--run-dir", type=Path, required=True,
        help="Path to Harbor run directory (e.g., runs/staging/ccb_contextbench_*)"
    )
    parser.add_argument(
        "--selection", type=Path, default=None,
        help="Path to pilot selection JSON for task name mapping"
    )
    parser.add_argument(
        "--output", type=Path, default=REPO_ROOT / "results" / "contextbench_pilot",
        help="Output directory for trajectories"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    # Handle glob patterns in run-dir
    run_dirs = []
    if args.run_dir.exists():
        run_dirs = [args.run_dir]
    else:
        parent = args.run_dir.parent
        pattern = args.run_dir.name
        if parent.exists():
            run_dirs = sorted(parent.glob(pattern))

    if not run_dirs:
        log.error("No run directories found matching: %s", args.run_dir)
        sys.exit(1)

    total_stats = {"baseline": 0, "mcp": 0, "skipped": 0, "no_match": 0}
    for rd in run_dirs:
        log.info("Processing: %s", rd)
        stats = convert_run(rd, args.output, args.selection)
        for k, v in stats.items():
            total_stats[k] += v

    print(f"\n=== Conversion Complete ===")
    print(f"Baseline trajectories: {total_stats['baseline']}")
    print(f"MCP trajectories:      {total_stats['mcp']}")
    print(f"No instance_id match:  {total_stats['no_match']}")
    print(f"Output:                {args.output}")


if __name__ == "__main__":
    main()
