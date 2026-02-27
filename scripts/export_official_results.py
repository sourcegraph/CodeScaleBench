#!/usr/bin/env python3
"""Export GitHub-friendly official run summaries with parsed trace views.

Builds a static bundle from runs/official with:
- README.md summary tables
- Per-run markdown pages
- Per-task markdown pages with parsed trace/tool details
- data/official_results.json (machine-readable)
- index.html (local browser UI)

Intended for publishing valid scored official runs and allowing local browsing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from config_utils import discover_configs, is_mcp_config
from official_runs import top_level_run_dirs, load_manifest, tracked_run_dirs_from_manifest

SKIP_DIR_PARTS = {"retrieval_events", "archive", "__archived", "__broken_verifier", "validation_test"}
TRANSCRIPT_CANDIDATES = (
    "claude-code.txt",
    "gemini-code.txt",
    "openhands-code.txt",
    "transcript.jsonl",
)
AUDIT_EVENT_LIMIT = 200


@dataclass
class TaskRecord:
    run_dir: str
    config: str
    task_name: str
    task_dir: str
    status: str
    reward: float
    timed_out: bool
    wall_clock_seconds: float | None
    agent_execution_seconds: float | None
    input_tokens: int | None
    output_tokens: int | None
    cache_tokens: int | None
    tool_calls_total: int | None
    tool_calls_mcp: int | None
    tool_calls_local: int | None
    mcp_ratio: float | None
    search_calls_keyword: int | None
    search_calls_nls: int | None
    search_calls_deepsearch: int | None
    tool_calls_by_name: dict[str, int] | None
    sample_tool_calls: list[dict[str, str]]
    trace_available: dict[str, bool]
    trace_paths: dict[str, str | None]
    checksums: dict[str, str | None]
    audit_page: str | None = None


def _safe_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _sha256_file(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _parse_iso_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _elapsed_seconds(started_at: Any, finished_at: Any) -> float | None:
    start_dt = _parse_iso_timestamp(started_at)
    end_dt = _parse_iso_timestamp(finished_at)
    if start_dt is None or end_dt is None:
        return None
    return max((end_dt - start_dt).total_seconds(), 0.0)


def _task_name_from_dir(task_dir: Path) -> str:
    name = task_dir.name
    if "__" in name:
        return name.rsplit("__", 1)[0]
    return name


def _is_task_result_payload(data: dict[str, Any]) -> bool:
    if not isinstance(data, dict):
        return False
    if "task_name" in data or "trial_name" in data:
        return True
    if "verifier_result" in data and "agent_result" in data:
        return True
    return False


def _iter_task_dirs(config_dir: Path) -> list[Path]:
    task_dirs: list[Path] = []
    for result_path in sorted(config_dir.rglob("result.json")):
        if any(part in SKIP_DIR_PARTS for part in result_path.parts):
            continue
        try:
            payload = json.loads(result_path.read_text())
        except Exception:
            continue
        if not _is_task_result_payload(payload):
            continue
        task_dirs.append(result_path.parent)
    return task_dirs


def _extract_reward_and_status(result_payload: dict[str, Any]) -> tuple[float | None, str]:
    exception_info = result_payload.get("exception_info")
    verifier = result_payload.get("verifier_result") or {}
    rewards = verifier.get("rewards") if isinstance(verifier, dict) else {}
    rewards = rewards if isinstance(rewards, dict) else {}
    reward = _safe_float(rewards.get("reward"))
    if reward is None:
        reward = _safe_float(rewards.get("score"))

    if exception_info is not None:
        return reward, "errored"
    if reward is None:
        return None, "unknown"
    if reward > 0:
        return reward, "passed"
    return reward, "failed"


def _load_task_metrics(task_dir: Path) -> dict[str, Any] | None:
    path = task_dir / "task_metrics.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _find_trace_paths(task_dir: Path) -> dict[str, str | None]:
    agent_dir = task_dir / "agent"
    trajectory = agent_dir / "trajectory.json"

    transcript: Path | None = None
    if agent_dir.is_dir():
        for name in TRANSCRIPT_CANDIDATES:
            candidate = agent_dir / name
            if candidate.is_file():
                transcript = candidate
                break

    rel_traj = str(trajectory.relative_to(PROJECT_ROOT)) if trajectory.is_file() else None
    rel_tx = str(transcript.relative_to(PROJECT_ROOT)) if transcript and transcript.is_file() else None
    return {
        "trajectory": rel_traj,
        "transcript": rel_tx,
    }


def _parse_transcript(
    transcript_path: Path,
    max_examples: int,
) -> tuple[dict[str, int], list[dict[str, str]], dict[str, Any]]:
    counts: Counter[str] = Counter()
    examples: list[dict[str, str]] = []
    events: list[dict[str, Any]] = []
    line_count = 0
    json_line_count = 0
    if not transcript_path.is_file():
        return {}, examples, {
            "line_count": 0,
            "json_line_count": 0,
            "tool_event_count": 0,
            "tool_events": [],
        }

    try:
        lines = transcript_path.read_text(errors="replace").splitlines()
    except Exception:
        return {}, examples, {
            "line_count": 0,
            "json_line_count": 0,
            "tool_event_count": 0,
            "tool_events": [],
        }

    for line in lines:
        line_count += 1
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        json_line_count += 1

        if payload.get("type") != "assistant":
            continue
        ts = payload.get("timestamp")
        message = payload.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue

        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "tool_use":
                continue
            tool_name = str(item.get("name") or "unknown")
            counts[tool_name] += 1
            if len(events) < AUDIT_EVENT_LIMIT:
                events.append(
                    {
                        "timestamp": ts if isinstance(ts, str) else None,
                        "tool": tool_name,
                    }
                )
            if len(examples) < max_examples:
                examples.append({"tool": tool_name})

    return dict(counts), examples, {
        "line_count": line_count,
        "json_line_count": json_line_count,
        "tool_event_count": sum(counts.values()),
        "tool_events": events,
    }


def _parse_trajectory(trajectory_path: Path) -> dict[str, Any]:
    if not trajectory_path.is_file():
        return {
            "step_count": 0,
            "tool_event_count": 0,
            "tool_counts_by_name": {},
            "tool_events": [],
        }
    try:
        payload = json.loads(trajectory_path.read_text())
    except Exception:
        return {
            "step_count": 0,
            "tool_event_count": 0,
            "tool_counts_by_name": {},
            "tool_events": [],
        }
    steps = payload.get("steps")
    if not isinstance(steps, list):
        steps = []

    counts: Counter[str] = Counter()
    events: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_id = step.get("step_id")
        timestamp = step.get("timestamp")
        tool_calls = step.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            tool_name = str(call.get("tool_name") or call.get("name") or "unknown")
            counts[tool_name] += 1
            if len(events) < AUDIT_EVENT_LIMIT:
                events.append(
                    {
                        "step_id": step_id if isinstance(step_id, int) else None,
                        "timestamp": timestamp if isinstance(timestamp, str) else None,
                        "tool": tool_name,
                    }
                )
    return {
        "step_count": len(steps),
        "tool_event_count": sum(counts.values()),
        "tool_counts_by_name": dict(counts),
        "tool_events": events,
    }


def _extract_task_record(
    run_dir_name: str,
    config_name: str,
    task_dir: Path,
    max_examples: int,
) -> tuple[TaskRecord, dict[str, Any]] | None:
    result_path = task_dir / "result.json"
    if not result_path.is_file():
        return None

    try:
        result_payload = json.loads(result_path.read_text())
    except Exception:
        return None

    reward, status = _extract_reward_and_status(result_payload)
    if reward is None or status not in {"passed", "failed"}:
        return None

    task_name = str(result_payload.get("task_name") or _task_name_from_dir(task_dir))

    agent_result = result_payload.get("agent_result") or {}
    if not isinstance(agent_result, dict):
        agent_result = {}

    timed_out = bool(result_payload.get("timed_out") or result_payload.get("timeout"))

    wall_clock_seconds = _safe_float(result_payload.get("wall_clock_seconds"))
    if wall_clock_seconds is None:
        wall_clock_seconds = _elapsed_seconds(
            result_payload.get("started_at"),
            result_payload.get("finished_at"),
        )

    agent_exec = result_payload.get("agent_execution") or {}
    agent_execution_seconds = _safe_float(agent_exec.get("elapsed_seconds")) if isinstance(agent_exec, dict) else None
    if agent_execution_seconds is None and isinstance(agent_exec, dict):
        agent_execution_seconds = _elapsed_seconds(
            agent_exec.get("started_at"),
            agent_exec.get("finished_at"),
        )

    input_tokens = _safe_int(agent_result.get("n_input_tokens"))
    output_tokens = _safe_int(agent_result.get("n_output_tokens"))
    cache_tokens = _safe_int(
        agent_result.get("n_cache_tokens", agent_result.get("cache_creation_input_tokens"))
    )

    task_metrics = _load_task_metrics(task_dir)

    tool_calls_total = _safe_int(task_metrics.get("tool_calls_total")) if task_metrics else None
    tool_calls_mcp = _safe_int(task_metrics.get("tool_calls_mcp")) if task_metrics else None
    tool_calls_local = _safe_int(task_metrics.get("tool_calls_local")) if task_metrics else None
    mcp_ratio = _safe_float(task_metrics.get("mcp_ratio")) if task_metrics else None

    search_calls_keyword = _safe_int(task_metrics.get("search_calls_keyword")) if task_metrics else None
    search_calls_nls = _safe_int(task_metrics.get("search_calls_nls")) if task_metrics else None
    search_calls_deepsearch = _safe_int(task_metrics.get("search_calls_deepsearch")) if task_metrics else None

    tool_calls_by_name = None
    if task_metrics and isinstance(task_metrics.get("tool_calls_by_name"), dict):
        tool_calls_by_name = {
            str(k): int(v)
            for k, v in task_metrics["tool_calls_by_name"].items()
            if isinstance(v, (int, float))
        }

    trace_paths = _find_trace_paths(task_dir)
    trajectory_path = PROJECT_ROOT / trace_paths["trajectory"] if trace_paths["trajectory"] else None
    transcript_path = PROJECT_ROOT / trace_paths["transcript"] if trace_paths["transcript"] else None
    parsed_counts, sample_tool_calls, transcript_audit = (
        _parse_transcript(transcript_path, max_examples)
        if transcript_path
        else ({}, [], {"line_count": 0, "json_line_count": 0, "tool_event_count": 0, "tool_events": []})
    )
    trajectory_audit = _parse_trajectory(trajectory_path) if trajectory_path else {
        "step_count": 0,
        "tool_event_count": 0,
        "tool_counts_by_name": {},
        "tool_events": [],
    }

    # Fallback to transcript-derived tool counts when task_metrics is missing.
    if tool_calls_by_name is None and parsed_counts:
        tool_calls_by_name = parsed_counts
    if tool_calls_total is None and parsed_counts:
        tool_calls_total = sum(parsed_counts.values())
    if tool_calls_mcp is None and parsed_counts:
        tool_calls_mcp = sum(v for k, v in parsed_counts.items() if k.startswith("mcp__sourcegraph__"))
    if tool_calls_local is None and parsed_counts and tool_calls_mcp is not None and tool_calls_total is not None:
        tool_calls_local = max(tool_calls_total - tool_calls_mcp, 0)
    if mcp_ratio is None and tool_calls_total and tool_calls_mcp is not None and tool_calls_total > 0:
        mcp_ratio = tool_calls_mcp / tool_calls_total

    rel_task_dir = str(task_dir.relative_to(PROJECT_ROOT))

    result_sha = _sha256_file(result_path)
    traj_sha = _sha256_file(trajectory_path) if trajectory_path else None
    tx_sha = _sha256_file(transcript_path) if transcript_path else None

    record = TaskRecord(
        run_dir=run_dir_name,
        config=config_name,
        task_name=task_name,
        task_dir=rel_task_dir,
        status=status,
        reward=reward,
        timed_out=timed_out,
        wall_clock_seconds=wall_clock_seconds,
        agent_execution_seconds=agent_execution_seconds,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_tokens=cache_tokens,
        tool_calls_total=tool_calls_total,
        tool_calls_mcp=tool_calls_mcp,
        tool_calls_local=tool_calls_local,
        mcp_ratio=mcp_ratio,
        search_calls_keyword=search_calls_keyword,
        search_calls_nls=search_calls_nls,
        search_calls_deepsearch=search_calls_deepsearch,
        tool_calls_by_name=tool_calls_by_name,
        sample_tool_calls=sample_tool_calls,
        trace_available={
            "trajectory": trace_paths["trajectory"] is not None,
            "transcript": trace_paths["transcript"] is not None,
        },
        trace_paths=trace_paths,
        checksums={
            "result_json_sha256": result_sha,
            "trajectory_sha256": traj_sha,
            "transcript_sha256": tx_sha,
        },
    )

    audit_payload = {
        "provenance": {
            "run_dir": run_dir_name,
            "config": config_name,
            "task_name": task_name,
            "task_dir": str(task_dir.relative_to(PROJECT_ROOT)),
            "result_path": str(result_path.relative_to(PROJECT_ROOT)),
            "trace_paths": trace_paths,
            "checksums": record.checksums,
        },
        "score": {
            "status": status,
            "reward": reward,
            "timed_out": timed_out,
        },
        "metrics": {
            "wall_clock_seconds": wall_clock_seconds,
            "agent_execution_seconds": agent_execution_seconds,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_tokens": cache_tokens,
            "tool_calls_total": tool_calls_total,
            "tool_calls_mcp": tool_calls_mcp,
            "tool_calls_local": tool_calls_local,
            "mcp_ratio": mcp_ratio,
            "search_calls_keyword": search_calls_keyword,
            "search_calls_nls": search_calls_nls,
            "search_calls_deepsearch": search_calls_deepsearch,
            "tool_calls_by_name": tool_calls_by_name,
        },
        "parsed_trace": {
            "transcript": transcript_audit,
            "trajectory": trajectory_audit,
        },
    }
    return record, audit_payload


def _slug(text: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", text.strip())
    normalized = normalized.strip("-")
    return normalized or "item"


def _fmt_float(value: float | None, digits: int = 3) -> str:
    if value is None:
        return "-"
    return f"{value:.{digits}f}"


def _fmt_int(value: int | None) -> str:
    if value is None:
        return "-"
    return f"{value:,}"


def _to_task_dict(record: TaskRecord, task_page: str) -> dict[str, Any]:
    return {
        "run_dir": record.run_dir,
        "config": record.config,
        "task_name": record.task_name,
        "task_dir": record.task_dir,
        "status": record.status,
        "reward": record.reward,
        "timed_out": record.timed_out,
        "wall_clock_seconds": record.wall_clock_seconds,
        "agent_execution_seconds": record.agent_execution_seconds,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "cache_tokens": record.cache_tokens,
        "tool_calls_total": record.tool_calls_total,
        "tool_calls_mcp": record.tool_calls_mcp,
        "tool_calls_local": record.tool_calls_local,
        "mcp_ratio": record.mcp_ratio,
        "search_calls_keyword": record.search_calls_keyword,
        "search_calls_nls": record.search_calls_nls,
        "search_calls_deepsearch": record.search_calls_deepsearch,
        "tool_calls_by_name": record.tool_calls_by_name,
        "sample_tool_calls": record.sample_tool_calls,
        "trace_available": record.trace_available,
        "trace_paths": record.trace_paths,
        "checksums": record.checksums,
        "audit_page": record.audit_page,
        "task_page": task_page,
    }


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _build_task_page(record: TaskRecord) -> str:
    lines: list[str] = []
    lines.append(f"# {record.task_name} ({record.config})")
    lines.append("")
    lines.append(f"- Run: `{record.run_dir}`")
    lines.append(f"- Status: `{record.status}`")
    lines.append(f"- Reward: `{_fmt_float(record.reward, 4)}`")
    if record.audit_page:
        lines.append(f"- Audit JSON: [link](../{record.audit_page})")
    lines.append(f"- Trajectory available: `{record.trace_available['trajectory']}`")
    lines.append(f"- Transcript available: `{record.trace_available['transcript']}`")
    lines.append("")

    lines.append("## Metrics")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---:|")
    lines.append(f"| Wall clock seconds | {_fmt_float(record.wall_clock_seconds, 1)} |")
    lines.append(f"| Agent execution seconds | {_fmt_float(record.agent_execution_seconds, 1)} |")
    lines.append(f"| Input tokens | {_fmt_int(record.input_tokens)} |")
    lines.append(f"| Output tokens | {_fmt_int(record.output_tokens)} |")
    lines.append(f"| Cache tokens | {_fmt_int(record.cache_tokens)} |")
    lines.append(f"| Tool calls (total) | {_fmt_int(record.tool_calls_total)} |")
    lines.append(f"| Tool calls (MCP) | {_fmt_int(record.tool_calls_mcp)} |")
    lines.append(f"| Tool calls (local) | {_fmt_int(record.tool_calls_local)} |")
    lines.append(f"| MCP ratio | {_fmt_float(record.mcp_ratio, 3)} |")
    lines.append(f"| keyword_search calls | {_fmt_int(record.search_calls_keyword)} |")
    lines.append(f"| nls_search calls | {_fmt_int(record.search_calls_nls)} |")
    lines.append(f"| deepsearch calls | {_fmt_int(record.search_calls_deepsearch)} |")
    lines.append(f"| `result.json` SHA256 | `{record.checksums.get('result_json_sha256') or '-'}` |")
    lines.append(f"| `trajectory.json` SHA256 | `{record.checksums.get('trajectory_sha256') or '-'}` |")
    lines.append(f"| transcript SHA256 | `{record.checksums.get('transcript_sha256') or '-'}` |")
    lines.append("")

    if record.tool_calls_by_name:
        lines.append("## Tool Breakdown")
        lines.append("")
        lines.append("| Tool | Calls |")
        lines.append("|---|---:|")
        for tool, count in sorted(record.tool_calls_by_name.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"| `{tool}` | {count} |")
        lines.append("")

    if record.sample_tool_calls:
        lines.append("## Parsed Trace Samples")
        lines.append("")
        lines.append("| Tool |")
        lines.append("|---|")
        for sample in record.sample_tool_calls:
            tool = sample["tool"].replace("|", "\\|")
            lines.append(f"| `{tool}` |")
        lines.append("")

    return "\n".join(lines)


def _build_run_page(run_dir: str, config_tasks: dict[str, list[dict[str, Any]]]) -> str:
    lines: list[str] = []
    lines.append(f"# {run_dir}")
    lines.append("")

    for config, tasks in sorted(config_tasks.items()):
        rewards = [t["reward"] for t in tasks]
        passes = sum(1 for t in tasks if t["status"] == "passed")
        mean_reward = statistics.mean(rewards) if rewards else 0.0
        pass_rate = (passes / len(tasks)) if tasks else 0.0

        lines.append(f"## {config}")
        lines.append("")
        lines.append(f"- Valid tasks: `{len(tasks)}`")
        lines.append(f"- Mean reward: `{mean_reward:.3f}`")
        lines.append(f"- Pass rate: `{pass_rate:.3f}`")
        lines.append("")

        lines.append("| Task | Status | Reward | MCP Ratio | Tool Calls | Trace |")
        lines.append("|---|---|---:|---:|---:|---|")

        tasks_sorted = sorted(tasks, key=lambda x: (x["status"], x["task_name"]))
        for task in tasks_sorted:
            trace = []
            if task["trace_available"]["trajectory"]:
                trace.append("traj")
            if task["trace_available"]["transcript"]:
                trace.append("tx")
            trace_label = ", ".join(trace) if trace else "-"
            lines.append(
                "| "
                f"[{task['task_name']}]({task['task_page']}) | "
                f"`{task['status']}` | "
                f"{task['reward']:.3f} | "
                f"{_fmt_float(task['mcp_ratio'])} | "
                f"{_fmt_int(task['tool_calls_total'])} | "
                f"{trace_label} |"
            )
        lines.append("")

    return "\n".join(lines)


def _build_root_readme(run_summaries: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    generated = datetime.now(timezone.utc).isoformat()
    lines.append("# Official Results Browser")
    lines.append("")
    lines.append("This bundle is generated from `runs/official/` and includes only valid scored tasks (`passed`/`failed` with numeric reward).")
    lines.append("")
    lines.append(f"Generated: `{generated}`")
    lines.append("")
    lines.append("## Local Browse")
    lines.append("")
    lines.append("```bash")
    lines.append("python3 scripts/export_official_results.py --serve")
    lines.append("```")
    lines.append("")
    lines.append("## Run/Config Summary")
    lines.append("")
    lines.append("| Run | Config | Valid Tasks | Mean Reward | Pass Rate |")
    lines.append("|---|---|---:|---:|---:|")
    for row in run_summaries:
        lines.append(
            f"| [{row['run_dir']}](runs/{row['run_page']}) | `{row['config']}` | "
            f"{row['task_count']} | {row['mean_reward']:.3f} | {row['pass_rate']:.3f} |"
        )
    lines.append("")
    lines.append("`index.html`, `data/official_results.json`, and `audits/*.json` provide GitHub-auditable artifacts.")
    return "\n".join(lines)


def _build_index_html() -> str:
    return """<!doctype html>
<html lang=\"en\"> 
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Official Results Browser</title>
  <style>
    :root { --bg:#0f1419; --panel:#182028; --text:#eef3f8; --muted:#9bb0c3; --accent:#47d18c; --warn:#ffcc66; }
    body { margin:0; font-family: ui-sans-serif, system-ui, sans-serif; background:var(--bg); color:var(--text); }
    .wrap { max-width: 1180px; margin: 0 auto; padding: 20px; }
    .controls { display:flex; gap:12px; flex-wrap:wrap; margin-bottom: 14px; }
    select,input { background:var(--panel); color:var(--text); border:1px solid #2e3d4a; border-radius:8px; padding:8px; }
    table { width:100%; border-collapse: collapse; background:var(--panel); border-radius:10px; overflow:hidden; }
    th,td { border-bottom: 1px solid #2d3a45; padding: 8px 10px; text-align:left; font-size: 13px; }
    th { color: var(--muted); }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
    a { color: var(--accent); text-decoration: none; }
    .pill { padding:2px 8px; border-radius:999px; font-size:12px; }
    .passed { background: rgba(71,209,140,0.2); }
    .failed { background: rgba(255,204,102,0.2); }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1>Official Results Browser</h1>
    <div class=\"controls\">
      <select id=\"runFilter\"><option value=\"\">All runs</option></select>
      <select id=\"configFilter\"><option value=\"\">All configs</option></select>
      <select id=\"statusFilter\"><option value=\"\">All statuses</option><option>passed</option><option>failed</option></select>
      <input id=\"taskSearch\" placeholder=\"Search task\" />
    </div>
    <table>
      <thead><tr><th>Run</th><th>Config</th><th>Task</th><th>Status</th><th>Reward</th><th>MCP ratio</th><th>Tools</th><th>Trace</th></tr></thead>
      <tbody id=\"rows\"></tbody>
    </table>
  </div>
  <script>
    const rowsEl = document.getElementById('rows');
    const runFilter = document.getElementById('runFilter');
    const configFilter = document.getElementById('configFilter');
    const statusFilter = document.getElementById('statusFilter');
    const taskSearch = document.getElementById('taskSearch');

    function fmt(v, d=3) { return (v===null || v===undefined) ? '-' : Number(v).toFixed(d); }

    fetch('data/official_results.json').then(r => r.json()).then(data => {
      const tasks = data.tasks || [];
      const runs = [...new Set(tasks.map(t => t.run_dir))].sort();
      const configs = [...new Set(tasks.map(t => t.config))].sort();
      runs.forEach(r => runFilter.add(new Option(r, r)));
      configs.forEach(c => configFilter.add(new Option(c, c)));

      const render = () => {
        const rf = runFilter.value;
        const cf = configFilter.value;
        const sf = statusFilter.value;
        const q = taskSearch.value.trim().toLowerCase();

        rowsEl.innerHTML = '';
        tasks
          .filter(t => (!rf || t.run_dir === rf) && (!cf || t.config === cf) && (!sf || t.status === sf) && (!q || t.task_name.toLowerCase().includes(q)))
          .slice(0, 1200)
          .forEach(t => {
            const tr = document.createElement('tr');
            const trace = `${t.trace_available.trajectory ? 'traj ' : ''}${t.trace_available.transcript ? 'tx' : ''}`.trim() || '-';
            tr.innerHTML = `
              <td class=\"mono\">${t.run_dir}</td>
              <td class=\"mono\">${t.config}</td>
              <td><a href=\"${t.task_page}\">${t.task_name}</a></td>
              <td><span class=\"pill ${t.status}\">${t.status}</span></td>
              <td>${fmt(t.reward,3)}</td>
              <td>${fmt(t.mcp_ratio,3)}</td>
              <td>${t.tool_calls_total ?? '-'}</td>
              <td>${trace}</td>
            `;
            rowsEl.appendChild(tr);
          });
      };

      runFilter.addEventListener('change', render);
      configFilter.addEventListener('change', render);
      statusFilter.addEventListener('change', render);
      taskSearch.addEventListener('input', render);
      render();
    });
  </script>
</body>
</html>
"""


def _serve_directory(directory: Path, port: int) -> None:
    os.chdir(directory)
    server = ThreadingHTTPServer(("127.0.0.1", port), SimpleHTTPRequestHandler)
    print(f"Serving {directory} at http://127.0.0.1:{port}/ (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


def build_export(
    runs_dir: Path,
    output_dir: Path,
    run_filter: set[str] | None,
    max_examples: int,
) -> dict[str, Any]:
    manifest_path = runs_dir / "MANIFEST.json"
    tracked: set[str] | None = None
    if manifest_path.is_file():
        manifest = load_manifest(manifest_path)
        tracked = tracked_run_dirs_from_manifest(manifest)

    run_dirs = top_level_run_dirs(runs_dir)
    if run_filter:
        run_dirs = [r for r in run_dirs if r.name in run_filter]
    if tracked is not None and tracked:
        run_dirs = [r for r in run_dirs if r.name in tracked]

    tasks_out: list[dict[str, Any]] = []

    tasks_dir = output_dir / "tasks"
    runs_pages_dir = output_dir / "runs"
    audits_dir = output_dir / "audits"

    for run_dir in run_dirs:
        configs = discover_configs(run_dir)
        for config in configs:
            config_dir = run_dir / config
            for task_dir in _iter_task_dirs(config_dir):
                extracted = _extract_task_record(run_dir.name, config, task_dir, max_examples)
                if extracted is None:
                    continue
                record, audit_payload = extracted

                task_slug = _slug(f"{run_dir.name}--{config}--{record.task_name}")
                audit_page_rel = f"audits/{task_slug}.json"
                record.audit_page = audit_page_rel
                _write_text(audits_dir / f"{task_slug}.json", json.dumps(audit_payload, indent=2, sort_keys=True))
                task_page_rel = f"tasks/{task_slug}.md"
                task_page_path = tasks_dir / f"{task_slug}.md"
                _write_text(task_page_path, _build_task_page(record))

                task_dict = _to_task_dict(record, task_page_rel)
                tasks_out.append(task_dict)

    run_summaries: list[dict[str, Any]] = []
    run_page_map: dict[str, str] = {}

    by_run: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for task in tasks_out:
        by_run[task["run_dir"]][task["config"]].append(task)

    for run_dir_name, config_map in sorted(by_run.items()):
        run_page_name = f"{_slug(run_dir_name)}.md"
        run_page_map[run_dir_name] = run_page_name
        run_page_path = runs_pages_dir / run_page_name

        # Adjust task links in page scope.
        page_config_map: dict[str, list[dict[str, Any]]] = {}
        for config, tasks in config_map.items():
            adjusted = []
            for t in tasks:
                copy_t = dict(t)
                copy_t["task_page"] = f"../{t['task_page']}"
                adjusted.append(copy_t)
            page_config_map[config] = adjusted

        _write_text(run_page_path, _build_run_page(run_dir_name, page_config_map))

        for config, tasks in sorted(config_map.items()):
            rewards = [t["reward"] for t in tasks]
            pass_count = sum(1 for t in tasks if t["status"] == "passed")
            mean_reward = statistics.mean(rewards) if rewards else 0.0
            pass_rate = pass_count / len(tasks) if tasks else 0.0
            run_summaries.append(
                {
                    "run_dir": run_dir_name,
                    "run_page": run_page_name,
                    "config": config,
                    "task_count": len(tasks),
                    "mean_reward": mean_reward,
                    "pass_rate": pass_rate,
                    "is_mcp_config": is_mcp_config(config),
                }
            )

    run_summaries.sort(key=lambda x: (x["run_dir"], x["config"]))

    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runs_dir": str(runs_dir),
        "run_count": len({r["run_dir"] for r in run_summaries}),
        "task_count": len(tasks_out),
        "run_summaries": run_summaries,
        "tasks": sorted(tasks_out, key=lambda t: (t["run_dir"], t["config"], t["task_name"])),
    }

    (output_dir / "data").mkdir(parents=True, exist_ok=True)
    _write_text(output_dir / "data" / "official_results.json", json.dumps(data, indent=2, sort_keys=True))
    _write_text(output_dir / "README.md", _build_root_readme(run_summaries))
    _write_text(output_dir / "index.html", _build_index_html())

    return data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runs-dir",
        default="./runs/official",
        help="Path to official runs directory (default: ./runs/official)",
    )
    parser.add_argument(
        "--output-dir",
        default="./docs/official_results",
        help="Directory to write static export bundle (default: ./docs/official_results)",
    )
    parser.add_argument(
        "--run",
        action="append",
        default=[],
        help="Optional run directory name to include (repeatable)",
    )
    parser.add_argument(
        "--max-trace-examples",
        type=int,
        default=12,
        help="Max parsed tool-use examples per task page (default: 12)",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Serve output directory locally after generation.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8008,
        help="Port for --serve (default: 8008)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    runs_dir = Path(args.runs_dir).resolve()
    output_dir = Path(args.output_dir).resolve()

    if not runs_dir.is_dir():
        print(f"[FAIL] runs dir not found: {runs_dir}")
        return 2

    run_filter = set(args.run) if args.run else None

    data = build_export(
        runs_dir=runs_dir,
        output_dir=output_dir,
        run_filter=run_filter,
        max_examples=max(0, args.max_trace_examples),
    )

    print(f"[OK] Wrote export bundle to: {output_dir}")
    print(f"      Runs: {data['run_count']}")
    print(f"      Valid scored tasks: {data['task_count']}")
    print(f"      Root summary: {output_dir / 'README.md'}")
    print(f"      JSON data: {output_dir / 'data' / 'official_results.json'}")
    print(f"      Local UI: {output_dir / 'index.html'}")

    if args.serve:
        _serve_directory(output_dir, args.port)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
