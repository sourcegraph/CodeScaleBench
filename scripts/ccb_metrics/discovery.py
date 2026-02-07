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
from .task_selection import normalize_benchmark_name
from .extractors import (
    extract_task_from_result_json,
    extract_task_tokens_from_transcript,
    extract_tool_usage_from_trajectory,
    extract_tool_usage_from_transcript,
    extract_swebench_partial_score,
    extract_reward_from_file,
    extract_run_config,
    extract_search_patterns_from_trajectory,
    extract_search_patterns_from_transcript,
    extract_code_changes_from_trajectory,
    extract_code_changes_from_transcript,
    calculate_cost_from_tokens,
    extract_error_fingerprint,
    extract_verifier_test_summary,
    extract_agent_return_code,
    extract_mcp_info,
    extract_instruction_length,
    extract_conversation_analysis_from_trajectory,
    extract_conversation_analysis_from_transcript,
    extract_mcp_latency_from_trajectory,
    classify_search_strategy,
)


def _infer_benchmark(run_name: str) -> str:
    """Infer benchmark name from run directory name.

    Examples:
        locobench_selected_opus_20260203_060731 -> locobench
        swebenchpro_selected_opus_20260203_160607 -> swebenchpro
        bigcode_mcp_opus_20260204_023501 -> bigcode
        pytorch_opus_20260203_160607 -> pytorch
        crossrepo_opus_20260204_133742 -> crossrepo
        dibench_opus_20260203_160835 -> dibench
        repoqa_opus_20260203_160835 -> repoqa
        sweperf_opus_20260203_160835 -> sweperf
        tac_opus_20260203_160607 -> tac
        k8s_docs_opus_20260203_160607 -> k8s_docs
    """
    name = run_name.lower()
    # Explicit prefixes (order matters — check longer prefixes first)
    prefixes = [
        ("locobench", "locobench"),
        ("swebench", "swebenchpro"),
        ("bigcode", "bigcode"),
        ("k8s_docs", "k8s_docs"),
        ("k8s", "k8s_docs"),
        ("kubernetes", "k8s_docs"),
        ("crossrepo", "crossrepo"),
        ("pytorch", "pytorch"),
        ("dibench", "dibench"),
        ("repoqa", "repoqa"),
        ("sweperf", "sweperf"),
        ("tac", "tac"),
    ]
    for prefix, bench in prefixes:
        if name.startswith(prefix):
            return bench
    # Fallback: take first segment before underscore-digit patterns
    m = re.match(r"^([a-z_]+?)(?:_\d|_mcp|_pro|_opus|_selected)", name)
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

    # Token data: prefer transcript (actual API usage) over result.json
    # (result.json n_input_tokens can include cumulative MCP result tokens,
    # inflating counts by 100x for MCP-enabled runs)
    transcript_path = task_dir / "agent" / "claude-code.txt"
    tokens = extract_task_tokens_from_transcript(transcript_path)
    if tokens.get("input_tokens") is not None:
        tm.input_tokens = tokens["input_tokens"]
        tm.output_tokens = tokens["output_tokens"]
        tm.cache_creation_tokens = tokens.get("cache_creation_input_tokens")
        tm.cache_read_tokens = tokens.get("cache_read_input_tokens")
    if tokens.get("total_cost_usd") is not None:
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

    # LLM Judge score (optional — stored alongside result.json)
    judge_result_path = task_dir / "judge_result.json"
    if judge_result_path.is_file():
        try:
            judge_data = json.loads(judge_result_path.read_text())
            tm.judge_score = judge_data.get("judge_score")
            tm.judge_rubric = judge_data.get("rubric")
            tm.judge_model = judge_data.get("judge_model")
        except (OSError, json.JSONDecodeError):
            pass

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

    # Search patterns — prefer trajectory, fall back to transcript
    search = extract_search_patterns_from_trajectory(trajectory_path)
    if search.get("search_calls_keyword") is None and search.get("search_calls_nls") is None:
        search = extract_search_patterns_from_transcript(transcript_path)

    if search.get("search_calls_keyword") is not None or search.get("search_calls_nls") is not None:
        tm.search_queries = search["search_queries"]
        tm.search_calls_keyword = search["search_calls_keyword"]
        tm.search_calls_nls = search["search_calls_nls"]
        tm.search_calls_deepsearch = search["search_calls_deepsearch"]
        tm.deepsearch_keyword_ratio = search["deepsearch_keyword_ratio"]
        tm.search_strategy_type = classify_search_strategy(
            search["search_calls_keyword"] or 0,
            search["search_calls_nls"] or 0,
            search["search_calls_deepsearch"] or 0,
        )

    # Code changes — prefer trajectory, fall back to transcript
    changes = extract_code_changes_from_trajectory(trajectory_path)
    if changes.get("files_modified") is None:
        changes = extract_code_changes_from_transcript(transcript_path)

    if changes.get("files_modified") is not None:
        tm.files_modified = changes["files_modified"]
        tm.lines_added = changes["lines_added"]
        tm.lines_removed = changes["lines_removed"]

    # Derived efficiency metrics
    if tm.input_tokens is not None and tm.output_tokens is not None and tm.output_tokens > 0:
        tm.input_output_ratio = tm.input_tokens / tm.output_tokens

    if tm.cache_read_tokens is not None and tm.cache_creation_tokens is not None:
        cache_total = tm.cache_read_tokens + tm.cache_creation_tokens
        if cache_total > 0:
            tm.cache_hit_rate = tm.cache_read_tokens / cache_total

    # Cost fallback: calculate from tokens if not already set
    if tm.cost_usd is None:
        tm.cost_usd = calculate_cost_from_tokens(
            tm.input_tokens, tm.output_tokens,
            tm.cache_creation_tokens, tm.cache_read_tokens,
        )

    # --- Tier 1: error & environment ---
    tm.error_fingerprint = extract_error_fingerprint(result_json)
    tm.agent_return_code = extract_agent_return_code(task_dir)

    mcp_info = extract_mcp_info(task_dir)
    tm.mcp_config_present = mcp_info["mcp_config_present"]
    tm.mcp_servers = mcp_info["mcp_servers"]

    tm.instruction_length_chars = extract_instruction_length(task_dir)

    test_stdout = task_dir / "verifier" / "test-stdout.txt"
    tm.verifier_test_summary = extract_verifier_test_summary(test_stdout, benchmark)

    # --- Tier 2: conversation analysis ---
    conv = extract_conversation_analysis_from_trajectory(trajectory_path)
    if conv.get("conversation_turns") is None:
        conv = extract_conversation_analysis_from_transcript(transcript_path)

    if conv.get("conversation_turns") is not None:
        tm.conversation_turns = conv["conversation_turns"]
        tm.tool_errors_total = conv["tool_errors_total"]
        tm.tool_errors_by_name = conv["tool_errors_by_name"]
        tm.backtrack_count = conv["backtrack_count"]
        tm.context_window_peak_pct = conv["context_window_peak_pct"]

    # If trajectory didn't give us context_window_peak, try transcript
    if tm.context_window_peak_pct is None and transcript_path.is_file():
        transcript_conv = extract_conversation_analysis_from_transcript(transcript_path)
        if transcript_conv.get("context_window_peak_pct") is not None:
            tm.context_window_peak_pct = transcript_conv["context_window_peak_pct"]

    # MCP latency from trajectory
    latency = extract_mcp_latency_from_trajectory(trajectory_path)
    tm.mcp_latency_p50_ms = latency["mcp_latency_p50_ms"]
    tm.mcp_latency_p95_ms = latency["mcp_latency_p95_ms"]

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
    harness_configs: dict[tuple[str, str], dict] = {}

    # Suffixes / patterns that mark a run directory as non-canonical
    _SKIP_PATTERNS = ("archive", "__broken", "__duplicate", "__all_errored", "__partial", "__integrated")

    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        run_name = run_dir.name
        if any(pat in run_name for pat in _SKIP_PATTERNS):
            continue
        benchmark = normalize_benchmark_name(_infer_benchmark(run_name))

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

                # Extract harness config from batch dir + first task transcript
                # Find a transcript path from the first task dir in this batch
                _transcript_for_config = None
                for _td in sorted(batch_dir.iterdir()):
                    if _is_task_dir(_td):
                        _candidate = _td / "agent" / "claude-code.txt"
                        if _candidate.is_file():
                            _transcript_for_config = _candidate
                            break

                hc = extract_run_config(batch_dir, _transcript_for_config)
                if key not in harness_configs or hc.get("model_name") is not None:
                    harness_configs[key] = hc

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
            harness_config=harness_configs.get((benchmark, config_name)),
        )
        results.append(run)

    return results
