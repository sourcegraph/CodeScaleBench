"""Discover Harbor runs and extract metrics from all tasks.

Walks the standard Harbor output structure:
    runs_dir/<run_name>/<config_name>/<batch_timestamp>/<task_id>__<hash>/

Groups tasks into RunMetrics by (benchmark, config_name) and returns a sorted
list. Stdlib only — no external dependencies.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .models import TaskMetrics, RunMetrics
from .extractors import (
    extract_task_from_result_json,
    extract_task_tokens_from_transcript,
    extract_tool_usage_from_trajectory,
    extract_tool_usage_from_transcript,
    extract_swebench_partial_score,
    extract_reward_from_file,
)


def _infer_benchmark(run_name: str) -> str:
    """Infer benchmark name from run directory name.

    Examples:
        locobench_50_tasks_20260127_170300 -> locobench
        swebenchpro_50_tasks_20260128_152150 -> swebenchpro
        bigcode_mcp_opus_20260131_130446 -> bigcode
    """
    name = run_name.lower()
    if name.startswith("locobench"):
        return "locobench"
    if name.startswith("swebench"):
        return "swebenchpro"
    if name.startswith("bigcode"):
        return "bigcode"
    if name.startswith("k8s") or name.startswith("kubernetes"):
        return "k8s_docs"
    # Fallback: take first segment before underscore-digit patterns
    m = re.match(r"^([a-z_]+?)(?:_\d|_mcp|_pro)", name)
    if m:
        return m.group(1)
    return run_name


def _is_batch_dir(d: Path) -> bool:
    """Check if directory matches the batch timestamp format YYYY-MM-DD__HH-MM-SS."""
    return bool(re.match(r"\d{4}-\d{2}-\d{2}__\d{2}-\d{2}-\d{2}$", d.name))


def _is_task_dir(d: Path) -> bool:
    """Check if directory looks like a task dir (contains __ hash separator)."""
    return d.is_dir() and "__" in d.name


def _extract_task_id(task_dir_name: str) -> str:
    """Extract the task ID from a directory name like 'task_id__hash'.

    The directory name is truncated, so we return the prefix before the
    last '__' separator (the hash is the last segment after __).
    """
    # Split on __ and rejoin all but the last segment (the hash)
    parts = task_dir_name.split("__")
    if len(parts) >= 2:
        return "__".join(parts[:-1])
    return task_dir_name


def _extract_model_from_config(batch_dir: Path) -> str:
    """Read model name from batch-level config.json."""
    config_path = batch_dir / "config.json"
    if not config_path.is_file():
        return "unknown"
    try:
        data = json.loads(config_path.read_text())
        # agents is a list; model_name is on each agent
        agents = data.get("agents") or []
        if agents and isinstance(agents, list):
            model = agents[0].get("model_name")
            if model:
                return model
        return "unknown"
    except (OSError, json.JSONDecodeError, IndexError):
        return "unknown"


def _extract_batch_timestamp(batch_dir: Path) -> str:
    """Convert batch dir name to a readable timestamp string."""
    # Format: 2026-01-27__17-03-08 -> 2026-01-27 17:03:08
    return batch_dir.name.replace("__", " ").replace("-", ":", 2).replace(":", "-", 2)


def _process_task_dir(
    task_dir: Path,
    benchmark: str,
    config_name: str,
    is_swebench: bool,
) -> Optional[TaskMetrics]:
    """Extract all metrics from a single task directory."""
    result_json = task_dir / "result.json"
    if not result_json.is_file():
        return None

    # Core extraction from result.json
    tm = extract_task_from_result_json(result_json, benchmark, config_name)

    # Fix task_id: use the one from result.json (task_name) if valid,
    # otherwise derive from directory name
    if tm.task_id == "unknown":
        tm.task_id = _extract_task_id(task_dir.name)

    # Token fallback from transcript
    if tm.input_tokens is None:
        transcript_path = task_dir / "agent" / "claude-code.txt"
        tokens = extract_task_tokens_from_transcript(transcript_path)
        if tokens.get("input_tokens") is not None:
            tm.input_tokens = tokens["input_tokens"]
            tm.output_tokens = tokens["output_tokens"]
            tm.cache_creation_tokens = tokens.get("cache_creation_input_tokens")
            tm.cache_read_tokens = tokens.get("cache_read_input_tokens")
        if tokens.get("total_cost_usd") is not None and tm.cost_usd is None:
            tm.cost_usd = tokens["total_cost_usd"]

    # Reward fallback from reward.txt
    if tm.reward is None:
        reward_path = task_dir / "verifier" / "reward.txt"
        reward = extract_reward_from_file(reward_path)
        if reward is not None:
            tm.reward = reward
            tm.status = "passed" if reward > 0 else "failed"

    # SWE-bench partial score
    if is_swebench:
        test_stdout = task_dir / "verifier" / "test-stdout.txt"
        partial = extract_swebench_partial_score(test_stdout)
        if partial is not None:
            tm.partial_score = partial

    # Tool usage — prefer trajectory, fall back to transcript
    trajectory_path = task_dir / "agent" / "trajectory.json"
    transcript_path = task_dir / "agent" / "claude-code.txt"
    tool_usage = extract_tool_usage_from_trajectory(trajectory_path)
    if tool_usage.get("tool_calls_total") is None:
        tool_usage = extract_tool_usage_from_transcript(transcript_path)

    if tool_usage.get("tool_calls_total") is not None:
        tm.tool_calls_total = tool_usage["tool_calls_total"]
        tm.tool_calls_mcp = tool_usage["tool_calls_mcp"]
        tm.tool_calls_local = tool_usage["tool_calls_local"]
        tm.tool_calls_by_name = tool_usage["tool_calls_by_name"]
        tm.mcp_ratio = tool_usage["mcp_ratio"]

    return tm


def discover_runs(runs_dir: str | Path) -> list[RunMetrics]:
    """Discover all runs under a Harbor official runs directory.

    Walks the structure:
        runs_dir/<run_name>/<config_name>/<batch_timestamp>/<task_id__hash>/

    Groups tasks into RunMetrics by (benchmark, config_name). Deduplicates
    tasks that appear in multiple batches (keeps the latest).

    Args:
        runs_dir: Path to the runs/official/ directory.

    Returns:
        List of RunMetrics sorted by (benchmark, config_name).
    """
    runs_dir = Path(runs_dir)
    if not runs_dir.is_dir():
        return []

    # Collect tasks grouped by (run_name, config_name)
    # Key: (benchmark, config_name) -> {task_id: TaskMetrics}
    grouped: dict[tuple[str, str], dict[str, TaskMetrics]] = {}
    run_metadata: dict[tuple[str, str], dict] = {}

    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        run_name = run_dir.name
        benchmark = _infer_benchmark(run_name)

        for config_dir in sorted(run_dir.iterdir()):
            if not config_dir.is_dir():
                continue
            config_name = config_dir.name

            key = (benchmark, config_name)
            if key not in grouped:
                grouped[key] = {}

            is_swebench = "swebench" in benchmark.lower()

            # Walk batch timestamp directories
            for batch_dir in sorted(config_dir.iterdir()):
                if not batch_dir.is_dir() or not _is_batch_dir(batch_dir):
                    continue

                # Extract model from config.json (use latest batch)
                model = _extract_model_from_config(batch_dir)
                timestamp = _extract_batch_timestamp(batch_dir)

                if key not in run_metadata or model != "unknown":
                    run_metadata[key] = {
                        "run_name": run_name,
                        "model": model,
                        "timestamp": timestamp,
                    }

                # Process each task directory
                for task_dir in sorted(batch_dir.iterdir()):
                    if not _is_task_dir(task_dir):
                        continue

                    tm = _process_task_dir(
                        task_dir, benchmark, config_name, is_swebench
                    )
                    if tm is not None:
                        # Deduplicate: later batches overwrite earlier ones
                        grouped[key][tm.task_id] = tm

    # Build RunMetrics from grouped data
    results: list[RunMetrics] = []
    for (benchmark, config_name), tasks_dict in sorted(grouped.items()):
        tasks = sorted(tasks_dict.values(), key=lambda t: t.task_id)
        meta = run_metadata.get((benchmark, config_name), {})

        run_id = f"{benchmark}_{config_name}"
        run = RunMetrics(
            run_id=run_id,
            benchmark=benchmark,
            config_name=config_name,
            model=meta.get("model", "unknown"),
            timestamp=meta.get("timestamp", "unknown"),
            task_count=len(tasks),
            tasks=tasks,
        )
        results.append(run)

    return results
