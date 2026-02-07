#!/usr/bin/env python3
"""Extract per-task metrics from a single Harbor task output directory.

Writes task_metrics.json into the task directory and prints a one-line summary.

Reuses extractors from scripts/ccb_metrics/ — same logic as discovery.py's
_process_task_dir() but callable as a standalone CLI.

Usage:
    python3 scripts/extract_task_metrics.py \
        --task-dir /path/to/task_id__hash/ \
        --benchmark ccb_crossrepo \
        --config baseline \
        [--selected-tasks configs/selected_benchmark_tasks.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure the scripts/ directory is on sys.path so ccb_metrics can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ccb_metrics.models import TaskMetrics
from ccb_metrics.extractors import (
    extract_task_from_result_json,
    extract_task_tokens_from_transcript,
    extract_swebench_partial_score,
    extract_tool_usage_from_trajectory,
    extract_tool_usage_from_transcript,
    extract_reward_from_file,
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
from ccb_metrics.task_selection import load_selected_tasks, build_task_index, enrich_task_metrics


def _extract_task_id(dirname: str) -> str:
    """Derive task_id from directory name (strip __hash suffix)."""
    parts = dirname.split("__")
    if len(parts) >= 2:
        return "__".join(parts[:-1])
    return dirname


def process_task_dir(
    task_dir: Path,
    benchmark: str,
    config_name: str,
) -> TaskMetrics | None:
    """Extract all metrics from a single task directory.

    Follows the same extraction pattern as discovery.py:_process_task_dir().
    """
    result_json = task_dir / "result.json"
    if not result_json.is_file():
        return None

    is_swebench = "swebench" in benchmark.lower()

    # Core extraction from result.json
    tm = extract_task_from_result_json(result_json, benchmark, config_name)

    # Fix task_id if needed
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

    # Reward fallback from reward.txt or reward.json
    if tm.reward is None:
        reward_path = task_dir / "verifier" / "reward.txt"
        reward = extract_reward_from_file(reward_path)
        if reward is None:
            # Some benchmarks (e.g. repoqa) write reward.json with a "score" key
            reward_json_path = task_dir / "verifier" / "reward.json"
            if reward_json_path.is_file():
                try:
                    rdata = json.loads(reward_json_path.read_text())
                    for key in ("reward", "score"):
                        if key in rdata:
                            reward = float(rdata[key])
                            break
                except (OSError, json.JSONDecodeError, TypeError, ValueError):
                    pass
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract per-task metrics from a Harbor task output directory."
    )
    parser.add_argument(
        "--task-dir", required=True, type=Path,
        help="Path to the task output directory (e.g. .../task_id__hash/)",
    )
    parser.add_argument(
        "--benchmark", required=True,
        help="Benchmark identifier (e.g. ccb_crossrepo)",
    )
    parser.add_argument(
        "--config", required=True,
        help="Configuration name (e.g. baseline, sourcegraph_full)",
    )
    parser.add_argument(
        "--selected-tasks", type=Path, default=None,
        help="Path to selected_benchmark_tasks.json for enrichment",
    )
    args = parser.parse_args()

    task_dir = args.task_dir.resolve()
    if not task_dir.is_dir():
        print(f"ERROR: Not a directory: {task_dir}", file=sys.stderr)
        sys.exit(1)

    tm = process_task_dir(task_dir, args.benchmark, args.config)
    if tm is None:
        print(f"ERROR: No result.json found in {task_dir}", file=sys.stderr)
        sys.exit(1)

    # Enrich with selection metadata if available
    if args.selected_tasks and args.selected_tasks.is_file():
        try:
            selection = load_selected_tasks(args.selected_tasks)
            task_index = build_task_index(selection)
            enrich_task_metrics(tm, task_index)
        except Exception as e:
            print(f"WARNING: Could not enrich metrics: {e}", file=sys.stderr)

    # Write task_metrics.json
    out_path = task_dir / "task_metrics.json"
    out_path.write_text(json.dumps(tm.to_dict(), indent=2) + "\n")

    # One-line summary to stdout
    reward_str = f"{tm.reward:.2f}" if tm.reward is not None else "n/a"
    tokens_str = f"{(tm.input_tokens or 0) + (tm.output_tokens or 0):,}" if tm.input_tokens is not None else "n/a"
    tools_str = str(tm.tool_calls_total) if tm.tool_calls_total is not None else "n/a"
    print(f"  {tm.task_id}: reward={reward_str} tokens={tokens_str} tools={tools_str} -> {out_path}")


if __name__ == "__main__":
    main()
