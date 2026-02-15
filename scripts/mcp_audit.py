#!/usr/bin/env python3
"""Comprehensive MCP Usage Audit for CodeContextBench.

Analyzes MCP tool usage, efficiency deltas, reward deltas, and timing
verification across all benchmark runs. Produces per-task and aggregate
analysis broken down by task type, codebase size, and task complexity.

Usage:
    python3 scripts/mcp_audit.py [--json] [--verbose]
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

RUNS_DIR = Path("/home/stephanie_jarmak/evals/custom_agents/agents/claudecode/runs/official")
SELECTION_FILE = Path(__file__).resolve().parent.parent / "configs" / "selected_benchmark_tasks.json"

SKIP_PATTERNS = ["__broken_verifier", "validation_test", "archive", "__archived"]
CONFIGS = ["baseline", "sourcegraph_base", "sourcegraph_full"]

DIR_PREFIX_TO_SUITE = {
    "bigcode_mcp_": "ccb_largerepo",
    "bigcode_sgcompare_": "ccb_largerepo",
    "codereview_": "ccb_codereview",
    "crossrepo_": "ccb_crossrepo",
    "dependeval_": "ccb_dependeval",
    "dibench_": "ccb_dibench",
    "investigation_": "ccb_investigation",
    "k8s_docs_": "ccb_k8sdocs",
    "linuxflbench_": "ccb_linuxflbench",
    "locobench_": "ccb_locobench",
    "pytorch_": "ccb_pytorch",
    "repoqa_": "ccb_repoqa",
    "swebenchpro_": "ccb_swebenchpro",
    "sweperf_": "ccb_sweperf",
    "tac_": "ccb_tac",
    "paired_rerun_dibench_": "ccb_dibench",
    "paired_rerun_crossrepo_": "ccb_crossrepo",
    "paired_rerun_pytorch_": "ccb_pytorch",
    "paired_rerun_": None,  # multi-suite paired reruns — infer from task_id
}

# Minimum agent execution seconds to consider a task valid (filters auth failures)
MIN_AGENT_TIME_SEC = 10

# MCP tool classification
MCP_TOOLS = {
    "mcp__sourcegraph__sg_keyword_search": "keyword_search",
    "mcp__sourcegraph__sg_nls_search": "nls_search",
    "mcp__sourcegraph__sg_deepsearch": "deepsearch",
    "mcp__sourcegraph__sg_deepsearch_read": "deepsearch_read",
    "mcp__sourcegraph__sg_read_file": "read_file",
    "mcp__sourcegraph__sg_list_files": "list_files",
    "mcp__sourcegraph__sg_list_repos": "list_repos",
    "mcp__sourcegraph__sg_find_references": "find_references",
    "mcp__sourcegraph__sg_go_to_definition": "go_to_definition",
    "mcp__sourcegraph__sg_commit_search": "commit_search",
    "mcp__sourcegraph__sg_diff_search": "diff_search",
    "mcp__sourcegraph__sg_compare_revisions": "compare_revisions",
    "mcp__sourcegraph__sg_get_contributor_repos": "get_contributor_repos",
    # Fallback patterns without sg_ prefix
    "mcp__sourcegraph__keyword_search": "keyword_search",
    "mcp__sourcegraph__nls_search": "nls_search",
    "mcp__sourcegraph__deepsearch": "deepsearch",
    "mcp__sourcegraph__deepsearch_read": "deepsearch_read",
    "mcp__sourcegraph__read_file": "read_file",
    "mcp__sourcegraph__list_files": "list_files",
    "mcp__sourcegraph__list_repos": "list_repos",
    "mcp__sourcegraph__find_references": "find_references",
    "mcp__sourcegraph__go_to_definition": "go_to_definition",
    "mcp__sourcegraph__commit_search": "commit_search",
    "mcp__sourcegraph__diff_search": "diff_search",
    "mcp__sourcegraph__compare_revisions": "compare_revisions",
    "mcp__sourcegraph__get_contributor_repos": "get_contributor_repos",
}

SEARCH_TOOLS = {"keyword_search", "nls_search", "deepsearch", "deepsearch_read"}
NAVIGATION_TOOLS = {"read_file", "list_files", "list_repos", "find_references",
                     "go_to_definition", "commit_search", "diff_search",
                     "compare_revisions", "get_contributor_repos"}

# Complexity buckets
LOC_BUCKETS = [
    (0, 50, "small (<50 LOC)"),
    (50, 200, "medium (50-200 LOC)"),
    (200, 500, "large (200-500 LOC)"),
    (500, float("inf"), "very_large (500+ LOC)"),
]

FILE_EDIT_BUCKETS = [
    (0, 2, "single_file (1)"),
    (2, 5, "few_files (2-4)"),
    (5, 10, "multi_file (5-9)"),
    (10, float("inf"), "many_files (10+)"),
]


def should_skip(dirname: str) -> bool:
    return any(pat in dirname for pat in SKIP_PATTERNS)


def _is_batch_timestamp(name: str) -> bool:
    return bool(re.match(r"\d{4}-\d{2}-\d{2}__\d{2}-\d{2}-\d{2}", name))


def _suite_from_run_dir(name: str) -> str | None:
    """Infer benchmark suite from run directory name."""
    for prefix, suite in DIR_PREFIX_TO_SUITE.items():
        if name.startswith(prefix):
            return suite  # May return None for multi-benchmark prefixes
    if name.startswith("swebenchpro_gapfill_"):
        return "ccb_swebenchpro"
    return None


def _suite_from_task_id(task_id: str) -> str | None:
    """Infer benchmark suite from task ID patterns."""
    if task_id.startswith("instance_"):
        return "ccb_swebenchpro"
    if task_id.startswith("sgt-"):
        return "ccb_pytorch"
    if task_id.startswith("big-code-"):
        return "ccb_largerepo"
    if task_id.startswith("dibench-"):
        return "ccb_dibench"
    if task_id.startswith("cr-"):
        return "ccb_codereview"
    if task_id.endswith("-doc-001"):
        return "ccb_k8sdocs"
    if task_id.startswith("lfl-"):
        return "ccb_linuxflbench"
    if task_id.startswith("bug_localization_") or task_id.startswith("refactor_rename_") or task_id.startswith("cross_file_reasoning_"):
        return "ccb_crossrepo"
    if "_expert_" in task_id:
        return "ccb_locobench"
    # DependEval patterns
    if task_id.startswith("multifile_editing-") or task_id.startswith("file_span_fix-") or task_id.startswith("dependency_recognition-"):
        return "ccb_dependeval"
    if task_id.startswith("repoqa-"):
        return "ccb_repoqa"
    if task_id.startswith("sweperf-"):
        return "ccb_sweperf"
    if task_id.startswith("tac-") or task_id.startswith("simple_test_"):
        return "ccb_tac"
    return None


def load_selection_metadata() -> dict:
    """Load task metadata from selected_benchmark_tasks.json."""
    if not SELECTION_FILE.is_file():
        return {}
    data = json.loads(SELECTION_FILE.read_text())
    index = {}
    for task in data.get("tasks", []):
        tid = task.get("task_id", "")
        index[tid] = task
    return index


def _is_valid_task(metrics: dict) -> bool:
    """Filter out auth failures and broken runs."""
    # Zero output tokens = no work done
    out = metrics.get("output_tokens")
    if out is not None and out == 0:
        return False
    # Very short agent time = auth failure or setup crash
    agent_time = metrics.get("agent_execution_seconds")
    if agent_time is not None and agent_time < MIN_AGENT_TIME_SEC:
        return False
    return True


def collect_task_metrics(paired_only: bool = False) -> list[dict]:
    """Walk all run dirs and collect task_metrics.json files with dedup.

    Args:
        paired_only: If True, only scan paired_rerun_* batch directories.
    """
    all_tasks = {}  # key: (suite, config, task_id) -> metrics dict

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir() or run_dir.name in ("archive", "MANIFEST.json"):
            continue
        if should_skip(run_dir.name):
            continue
        if paired_only and not run_dir.name.startswith("paired_rerun_"):
            continue

        for config_dir in sorted(run_dir.iterdir()):
            if not config_dir.is_dir():
                continue
            config_name = config_dir.name
            if config_name not in CONFIGS:
                continue

            for batch_dir in sorted(config_dir.iterdir()):
                if not batch_dir.is_dir():
                    continue
                if not _is_batch_timestamp(batch_dir.name):
                    continue

                for task_dir in sorted(batch_dir.iterdir()):
                    if not task_dir.is_dir():
                        continue

                    metrics_file = task_dir / "task_metrics.json"
                    if not metrics_file.is_file():
                        # Try to use result.json as fallback
                        result_file = task_dir / "result.json"
                        if not result_file.is_file():
                            continue
                        try:
                            metrics = _extract_from_result_json(result_file, config_name)
                        except Exception:
                            continue
                    else:
                        try:
                            metrics = json.loads(metrics_file.read_text())
                        except (json.JSONDecodeError, OSError):
                            continue

                    if not metrics:
                        continue

                    task_id = metrics.get("task_id", "")
                    benchmark = metrics.get("benchmark", "")

                    # Resolve blank/unknown benchmark from run_dir name or task_id
                    if not benchmark or benchmark == "unknown":
                        benchmark = _suite_from_run_dir(run_dir.name) or ""
                    if not benchmark or benchmark == "unknown" or benchmark == "__multi__":
                        benchmark = _suite_from_task_id(task_id) or "unknown"
                    metrics["benchmark"] = benchmark

                    cfg = metrics.get("config_name", config_name)
                    key = (benchmark, cfg, task_id)

                    # Timestamp-based dedup: keep latest
                    result_file = task_dir / "result.json"
                    started_at = ""
                    if result_file.is_file():
                        try:
                            rdata = json.loads(result_file.read_text())
                            started_at = rdata.get("started_at", "")
                        except Exception:
                            pass
                    metrics["_started_at"] = started_at
                    metrics["_task_dir"] = str(task_dir)

                    if key in all_tasks:
                        if started_at > all_tasks[key].get("_started_at", ""):
                            all_tasks[key] = metrics
                    else:
                        all_tasks[key] = metrics

    return list(all_tasks.values())


def _extract_from_result_json(result_file: Path, config_name: str) -> dict | None:
    """Minimal extraction from result.json when task_metrics.json is missing."""
    try:
        data = json.loads(result_file.read_text())
    except Exception:
        return None

    if "n_total_trials" in data and "task_name" not in data:
        return None  # batch-level

    task_name = data.get("task_name", "")
    agent_result = data.get("agent_result", {}) or {}
    verifier_result = data.get("verifier_result", {}) or {}
    rewards = verifier_result.get("rewards", {}) or {}
    reward = rewards.get("reward", rewards.get("score", 0.0))

    # Parse timing
    from datetime import datetime, timezone
    def parse_ts(s):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    agent_exec = data.get("agent_execution", {}) or {}
    ae_start = parse_ts(agent_exec.get("started_at"))
    ae_end = parse_ts(agent_exec.get("finished_at"))
    agent_exec_seconds = (ae_end - ae_start).total_seconds() if ae_start and ae_end else None

    env_setup = data.get("environment_setup", {}) or {}
    es_start = parse_ts(env_setup.get("started_at"))
    es_end = parse_ts(env_setup.get("finished_at"))
    env_setup_seconds = (es_end - es_start).total_seconds() if es_start and es_end else None

    verifier = data.get("verifier", {}) or {}
    v_start = parse_ts(verifier.get("started_at"))
    v_end = parse_ts(verifier.get("finished_at"))
    verifier_seconds = (v_end - v_start).total_seconds() if v_start and v_end else None

    wall_start = parse_ts(data.get("started_at"))
    wall_end = parse_ts(data.get("finished_at"))
    wall_clock = (wall_end - wall_start).total_seconds() if wall_start and wall_end else None

    return {
        "task_id": task_name,
        "benchmark": "",
        "config_name": config_name,
        "reward": reward if reward is not None else 0.0,
        "status": "passed" if reward and reward > 0 else "failed",
        "wall_clock_seconds": wall_clock,
        "agent_execution_seconds": agent_exec_seconds,
        "environment_setup_seconds": env_setup_seconds,
        "verifier_seconds": verifier_seconds,
        "input_tokens": agent_result.get("n_input_tokens", 0),
        "output_tokens": agent_result.get("n_output_tokens", 0),
        "cache_creation_tokens": agent_result.get("cache_creation_input_tokens", 0),
        "cache_read_tokens": agent_result.get("cache_read_input_tokens", 0),
        "tool_calls_total": 0,
        "tool_calls_mcp": 0,
        "mcp_ratio": 0.0,
    }


def bucket_loc(loc: int | None) -> str:
    if loc is None or loc <= 0:
        return "unknown"
    for lo, hi, label in LOC_BUCKETS:
        if lo <= loc < hi:
            return label
    return "unknown"


def bucket_files(n: int | None) -> str:
    if n is None or n <= 0:
        return "unknown"
    for lo, hi, label in FILE_EDIT_BUCKETS:
        if lo <= n < hi:
            return label
    return "unknown"


def safe_median(lst):
    return statistics.median(lst) if lst else None


def safe_mean(lst):
    return statistics.mean(lst) if lst else None


def trimmed_mean(lst, pct=0.1):
    """Compute trimmed mean, removing top/bottom pct of values."""
    if not lst:
        return None
    if len(lst) < 5:
        return statistics.mean(lst)
    s = sorted(lst)
    trim = max(1, int(len(s) * pct))
    trimmed = s[trim:-trim]
    return statistics.mean(trimmed) if trimmed else statistics.mean(lst)


def pct_delta(base, test):
    """Percent change from base to test."""
    if base is None or test is None or base == 0:
        return None
    return ((test - base) / abs(base)) * 100


def build_paired_analysis(all_metrics: list[dict], selection_meta: dict) -> dict:
    """Build paired (baseline vs MCP) analysis for every task."""
    # Group by (benchmark, task_id) -> {config: metrics}
    grouped = defaultdict(dict)
    for m in all_metrics:
        key = (m.get("benchmark", ""), m.get("task_id", ""))
        cfg = m.get("config_name", "")
        grouped[key][cfg] = m

    paired_results = []
    for (benchmark, task_id), configs in sorted(grouped.items()):
        bl = configs.get("baseline")
        sg_base = configs.get("sourcegraph_base")
        sg_full = configs.get("sourcegraph_full")

        # Get selection metadata
        sel = selection_meta.get(task_id, {})

        base_record = {
            "benchmark": benchmark,
            "task_id": task_id,
            "language": sel.get("language") or (bl or sg_base or sg_full or {}).get("language"),
            "difficulty": sel.get("difficulty") or (bl or sg_base or sg_full or {}).get("difficulty"),
            "category": sel.get("category") or (bl or sg_base or sg_full or {}).get("category"),
            "sdlc_phase": sel.get("sdlc_phase") or (bl or sg_base or sg_full or {}).get("sdlc_phase"),
            "mcp_benefit_score": sel.get("mcp_benefit_score") or (bl or sg_base or sg_full or {}).get("mcp_benefit_score"),
            "repo": sel.get("repo") or (bl or sg_base or sg_full or {}).get("repo"),
        }

        for cfg_name, cfg_data in [("baseline", bl), ("sourcegraph_base", sg_base), ("sourcegraph_full", sg_full)]:
            if cfg_data is None:
                base_record[f"{cfg_name}_reward"] = None
                base_record[f"{cfg_name}_agent_time"] = None
                base_record[f"{cfg_name}_wall_time"] = None
                base_record[f"{cfg_name}_env_setup_time"] = None
                base_record[f"{cfg_name}_verifier_time"] = None
                base_record[f"{cfg_name}_input_tokens"] = None
                base_record[f"{cfg_name}_output_tokens"] = None
                base_record[f"{cfg_name}_cache_creation_tokens"] = None
                base_record[f"{cfg_name}_cache_read_tokens"] = None
                base_record[f"{cfg_name}_cost_usd"] = None
                base_record[f"{cfg_name}_tool_calls_total"] = None
                base_record[f"{cfg_name}_tool_calls_mcp"] = None
                base_record[f"{cfg_name}_mcp_ratio"] = None
                base_record[f"{cfg_name}_tool_calls_by_name"] = None
                base_record[f"{cfg_name}_files_modified"] = None
                base_record[f"{cfg_name}_lines_added"] = None
                base_record[f"{cfg_name}_lines_removed"] = None
                base_record[f"{cfg_name}_conversation_turns"] = None
                base_record[f"{cfg_name}_context_window_peak_pct"] = None
                base_record[f"{cfg_name}_backtrack_count"] = None
                base_record[f"{cfg_name}_status"] = None
                base_record[f"{cfg_name}_search_calls_keyword"] = None
                base_record[f"{cfg_name}_search_calls_nls"] = None
                base_record[f"{cfg_name}_search_calls_deepsearch"] = None
                continue

            base_record[f"{cfg_name}_reward"] = cfg_data.get("reward")
            base_record[f"{cfg_name}_agent_time"] = cfg_data.get("agent_execution_seconds")
            base_record[f"{cfg_name}_wall_time"] = cfg_data.get("wall_clock_seconds")
            base_record[f"{cfg_name}_env_setup_time"] = cfg_data.get("environment_setup_seconds")
            base_record[f"{cfg_name}_verifier_time"] = cfg_data.get("verifier_seconds")
            base_record[f"{cfg_name}_input_tokens"] = cfg_data.get("input_tokens")
            base_record[f"{cfg_name}_output_tokens"] = cfg_data.get("output_tokens")
            base_record[f"{cfg_name}_cache_creation_tokens"] = cfg_data.get("cache_creation_tokens")
            base_record[f"{cfg_name}_cache_read_tokens"] = cfg_data.get("cache_read_tokens")
            base_record[f"{cfg_name}_cost_usd"] = cfg_data.get("cost_usd")
            base_record[f"{cfg_name}_tool_calls_total"] = cfg_data.get("tool_calls_total")
            base_record[f"{cfg_name}_tool_calls_mcp"] = cfg_data.get("tool_calls_mcp")
            base_record[f"{cfg_name}_mcp_ratio"] = cfg_data.get("mcp_ratio")
            base_record[f"{cfg_name}_tool_calls_by_name"] = cfg_data.get("tool_calls_by_name")
            base_record[f"{cfg_name}_files_modified"] = cfg_data.get("files_modified")
            base_record[f"{cfg_name}_lines_added"] = cfg_data.get("lines_added")
            base_record[f"{cfg_name}_lines_removed"] = cfg_data.get("lines_removed")
            base_record[f"{cfg_name}_conversation_turns"] = cfg_data.get("conversation_turns")
            base_record[f"{cfg_name}_context_window_peak_pct"] = cfg_data.get("context_window_peak_pct")
            base_record[f"{cfg_name}_backtrack_count"] = cfg_data.get("backtrack_count")
            base_record[f"{cfg_name}_status"] = cfg_data.get("status")
            base_record[f"{cfg_name}_search_calls_keyword"] = cfg_data.get("search_calls_keyword")
            base_record[f"{cfg_name}_search_calls_nls"] = cfg_data.get("search_calls_nls")
            base_record[f"{cfg_name}_search_calls_deepsearch"] = cfg_data.get("search_calls_deepsearch")

        # Compute deltas: SG_base vs baseline, SG_full vs baseline
        for mcp_cfg in ["sourcegraph_base", "sourcegraph_full"]:
            prefix = "sg_base" if "base" in mcp_cfg else "sg_full"
            bl_reward = base_record.get("baseline_reward")
            mcp_reward = base_record.get(f"{mcp_cfg}_reward")
            bl_time = base_record.get("baseline_agent_time")
            mcp_time = base_record.get(f"{mcp_cfg}_agent_time")
            bl_cost = base_record.get("baseline_cost_usd")
            mcp_cost = base_record.get(f"{mcp_cfg}_cost_usd")
            bl_output = base_record.get("baseline_output_tokens")
            mcp_output = base_record.get(f"{mcp_cfg}_output_tokens")

            base_record[f"{prefix}_reward_delta"] = (mcp_reward - bl_reward) if bl_reward is not None and mcp_reward is not None else None
            base_record[f"{prefix}_time_delta_pct"] = pct_delta(bl_time, mcp_time)
            base_record[f"{prefix}_cost_delta_pct"] = pct_delta(bl_cost, mcp_cost)
            base_record[f"{prefix}_output_delta_pct"] = pct_delta(bl_output, mcp_output)

            # Classify impact
            if bl_reward is not None and mcp_reward is not None:
                if mcp_reward > bl_reward:
                    base_record[f"{prefix}_impact"] = "mcp_helps_reward"
                elif mcp_reward < bl_reward:
                    base_record[f"{prefix}_impact"] = "mcp_hurts_reward"
                else:
                    base_record[f"{prefix}_impact"] = "neutral_reward"
            else:
                base_record[f"{prefix}_impact"] = "missing_data"

        # Complexity metrics (use baseline or any available)
        ref = bl or sg_base or sg_full or {}
        lines_added = ref.get("lines_added")
        lines_removed = ref.get("lines_removed")
        total_loc = (lines_added or 0) + (lines_removed or 0) if lines_added is not None or lines_removed is not None else None
        base_record["complexity_loc"] = total_loc
        base_record["complexity_loc_bucket"] = bucket_loc(total_loc)
        base_record["complexity_files_modified"] = ref.get("files_modified")
        base_record["complexity_files_bucket"] = bucket_files(ref.get("files_modified"))

        paired_results.append(base_record)

    return paired_results


def _timing_verification(paired: list[dict]) -> dict:
    """Verify timing methodology: agent_execution_seconds should exclude Docker build + verifier."""
    issues = []
    stats = {"total_tasks": 0, "has_agent_time": 0, "has_wall_time": 0,
             "has_env_setup": 0, "has_verifier": 0, "timing_consistent": 0,
             "timing_inconsistent": 0}

    for task in paired:
        for cfg in CONFIGS:
            agent_time = task.get(f"{cfg}_agent_time")
            wall_time = task.get(f"{cfg}_wall_time")
            env_time = task.get(f"{cfg}_env_setup_time")
            ver_time = task.get(f"{cfg}_verifier_time")

            if agent_time is None and wall_time is None:
                continue
            stats["total_tasks"] += 1

            if agent_time is not None:
                stats["has_agent_time"] += 1
            if wall_time is not None:
                stats["has_wall_time"] += 1
            if env_time is not None:
                stats["has_env_setup"] += 1
            if ver_time is not None:
                stats["has_verifier"] += 1

            # Verify: agent_time < wall_time (should exclude Docker + verifier)
            if agent_time is not None and wall_time is not None:
                if agent_time <= wall_time * 1.05:  # 5% tolerance for rounding
                    stats["timing_consistent"] += 1
                else:
                    stats["timing_inconsistent"] += 1
                    issues.append({
                        "task_id": task["task_id"],
                        "benchmark": task["benchmark"],
                        "config": cfg,
                        "agent_time": round(agent_time, 1),
                        "wall_time": round(wall_time, 1),
                        "env_setup": round(env_time, 1) if env_time else None,
                        "verifier": round(ver_time, 1) if ver_time else None,
                    })

            # Verify: wall ≈ env_setup + agent_setup + agent_execution + verifier
            if all(x is not None for x in [agent_time, wall_time, env_time, ver_time]):
                reconstructed = env_time + agent_time + ver_time
                gap = abs(wall_time - reconstructed)
                if gap > wall_time * 0.15:  # 15% tolerance (agent_setup not tracked)
                    issues.append({
                        "task_id": task["task_id"],
                        "benchmark": task["benchmark"],
                        "config": cfg,
                        "issue": "wall_time_reconstruction_gap",
                        "wall_time": round(wall_time, 1),
                        "reconstructed": round(reconstructed, 1),
                        "gap_seconds": round(gap, 1),
                        "gap_pct": round(gap / wall_time * 100, 1) if wall_time > 0 else None,
                    })

    return {
        "stats": stats,
        "issues": issues[:20],  # cap
    }


def _mcp_usage_analysis(paired: list[dict]) -> dict:
    """Analyze MCP tool usage patterns across MCP configs."""
    mcp_tool_totals = defaultdict(int)
    per_benchmark_mcp = defaultdict(lambda: {"total_mcp_calls": 0, "tasks_with_mcp": 0,
                                              "tasks_total": 0, "tool_breakdown": defaultdict(int)})
    mcp_ratio_by_config = defaultdict(list)
    mcp_calls_distribution = defaultdict(list)
    search_vs_nav = {"search": 0, "navigation": 0}

    for task in paired:
        for cfg in ["sourcegraph_base", "sourcegraph_full"]:
            mcp_calls = task.get(f"{cfg}_tool_calls_mcp")
            mcp_ratio = task.get(f"{cfg}_mcp_ratio")
            tool_by_name = task.get(f"{cfg}_tool_calls_by_name") or {}
            benchmark = task.get("benchmark", "")

            if mcp_calls is None:
                continue

            mcp_ratio_by_config[cfg].append(mcp_ratio or 0)
            mcp_calls_distribution[cfg].append(mcp_calls)

            bm = per_benchmark_mcp[(benchmark, cfg)]
            bm["tasks_total"] += 1
            bm["total_mcp_calls"] += mcp_calls
            if mcp_calls > 0:
                bm["tasks_with_mcp"] += 1

            # Classify individual MCP tools
            for tool_name, count in tool_by_name.items():
                canonical = MCP_TOOLS.get(tool_name)
                if canonical:
                    mcp_tool_totals[canonical] += count
                    bm["tool_breakdown"][canonical] += count
                    if canonical in SEARCH_TOOLS:
                        search_vs_nav["search"] += count
                    elif canonical in NAVIGATION_TOOLS:
                        search_vs_nav["navigation"] += count

    return {
        "mcp_tool_totals": dict(sorted(mcp_tool_totals.items(), key=lambda x: -x[1])),
        "search_vs_navigation": search_vs_nav,
        "per_benchmark": {
            f"{bm}/{cfg}": {
                "tasks_total": v["tasks_total"],
                "tasks_with_mcp": v["tasks_with_mcp"],
                "adoption_rate": round(v["tasks_with_mcp"] / v["tasks_total"], 3) if v["tasks_total"] > 0 else 0,
                "total_mcp_calls": v["total_mcp_calls"],
                "avg_mcp_calls": round(v["total_mcp_calls"] / v["tasks_total"], 1) if v["tasks_total"] > 0 else 0,
                "tool_breakdown": dict(sorted(v["tool_breakdown"].items(), key=lambda x: -x[1])),
            }
            for (bm, cfg), v in sorted(per_benchmark_mcp.items())
        },
        "mcp_ratio_stats": {
            cfg: {
                "mean": round(safe_mean(vals), 4) if vals else None,
                "median": round(safe_median(vals), 4) if vals else None,
                "max": round(max(vals), 4) if vals else None,
                "n_zero": sum(1 for v in vals if v == 0),
                "n_tasks": len(vals),
            }
            for cfg, vals in mcp_ratio_by_config.items()
        },
    }


def _efficiency_analysis(paired: list[dict]) -> dict:
    """Analyze time and cost efficiency deltas between baseline and MCP configs."""
    results = {}

    for prefix, cfg in [("sg_base", "sourcegraph_base"), ("sg_full", "sourcegraph_full")]:
        time_deltas = []
        cost_deltas = []
        output_deltas = []
        time_by_benchmark = defaultdict(list)
        cost_by_benchmark = defaultdict(list)

        for task in paired:
            td = task.get(f"{prefix}_time_delta_pct")
            cd = task.get(f"{prefix}_cost_delta_pct")
            od = task.get(f"{prefix}_output_delta_pct")
            bm = task.get("benchmark", "")

            if td is not None:
                time_deltas.append(td)
                time_by_benchmark[bm].append(td)
            if cd is not None:
                cost_deltas.append(cd)
                cost_by_benchmark[bm].append(cd)
            if od is not None:
                output_deltas.append(od)

        results[prefix] = {
            "time_delta_pct": {
                "mean": round(safe_mean(time_deltas), 1) if time_deltas else None,
                "trimmed_mean": round(trimmed_mean(time_deltas), 1) if time_deltas else None,
                "median": round(safe_median(time_deltas), 1) if time_deltas else None,
                "n_faster": sum(1 for d in time_deltas if d < -5),
                "n_neutral": sum(1 for d in time_deltas if -5 <= d <= 5),
                "n_slower": sum(1 for d in time_deltas if d > 5),
                "n_total": len(time_deltas),
            },
            "cost_delta_pct": {
                "mean": round(safe_mean(cost_deltas), 1) if cost_deltas else None,
                "trimmed_mean": round(trimmed_mean(cost_deltas), 1) if cost_deltas else None,
                "median": round(safe_median(cost_deltas), 1) if cost_deltas else None,
                "n_total": len(cost_deltas),
            },
            "output_tokens_delta_pct": {
                "mean": round(safe_mean(output_deltas), 1) if output_deltas else None,
                "trimmed_mean": round(trimmed_mean(output_deltas), 1) if output_deltas else None,
                "median": round(safe_median(output_deltas), 1) if output_deltas else None,
                "n_total": len(output_deltas),
            },
            "time_by_benchmark": {
                bm: {
                    "mean_delta_pct": round(safe_mean(vals), 1),
                    "trimmed_mean_pct": round(trimmed_mean(vals), 1),
                    "median_delta_pct": round(safe_median(vals), 1),
                    "n_tasks": len(vals),
                    "n_faster": sum(1 for d in vals if d < -5),
                    "n_slower": sum(1 for d in vals if d > 5),
                }
                for bm, vals in sorted(time_by_benchmark.items())
            },
            "cost_by_benchmark": {
                bm: {
                    "mean_delta_pct": round(safe_mean(vals), 1),
                    "n_tasks": len(vals),
                }
                for bm, vals in sorted(cost_by_benchmark.items())
            },
        }

    return results


def _reward_analysis(paired: list[dict]) -> dict:
    """Analyze reward deltas by benchmark, task type, complexity."""
    results = {}

    for prefix, cfg in [("sg_base", "sourcegraph_base"), ("sg_full", "sourcegraph_full")]:
        reward_deltas = []
        by_benchmark = defaultdict(list)
        by_difficulty = defaultdict(list)
        by_sdlc = defaultdict(list)
        by_loc_bucket = defaultdict(list)
        by_files_bucket = defaultdict(list)
        by_mcp_score = defaultdict(list)
        flips_positive = []  # baseline fail -> MCP pass
        flips_negative = []  # baseline pass -> MCP fail

        for task in paired:
            rd = task.get(f"{prefix}_reward_delta")
            if rd is None:
                continue
            reward_deltas.append(rd)
            bm = task.get("benchmark", "unknown")
            by_benchmark[bm].append(rd)
            diff = task.get("difficulty", "unknown") or "unknown"
            by_difficulty[diff].append(rd)
            sdlc = task.get("sdlc_phase", "unknown") or "unknown"
            by_sdlc[sdlc].append(rd)
            loc_b = task.get("complexity_loc_bucket", "unknown")
            by_loc_bucket[loc_b].append(rd)
            files_b = task.get("complexity_files_bucket", "unknown")
            by_files_bucket[files_b].append(rd)

            mcp_score = task.get("mcp_benefit_score")
            if mcp_score is not None:
                if mcp_score >= 0.8:
                    by_mcp_score["high (>=0.8)"].append(rd)
                elif mcp_score >= 0.6:
                    by_mcp_score["medium (0.6-0.8)"].append(rd)
                else:
                    by_mcp_score["low (<0.6)"].append(rd)

            # Track flips
            bl_r = task.get("baseline_reward")
            mcp_r = task.get(f"{cfg}_reward")
            if bl_r is not None and mcp_r is not None:
                bl_pass = bl_r > 0
                mcp_pass = mcp_r > 0
                if not bl_pass and mcp_pass:
                    flips_positive.append(task)
                elif bl_pass and not mcp_pass:
                    flips_negative.append(task)

        results[prefix] = {
            "overall": {
                "mean_delta": round(safe_mean(reward_deltas), 4) if reward_deltas else None,
                "median_delta": round(safe_median(reward_deltas), 4) if reward_deltas else None,
                "n_improved": sum(1 for d in reward_deltas if d > 0.01),
                "n_neutral": sum(1 for d in reward_deltas if -0.01 <= d <= 0.01),
                "n_degraded": sum(1 for d in reward_deltas if d < -0.01),
                "n_total": len(reward_deltas),
            },
            "flips": {
                "positive_flips": len(flips_positive),
                "negative_flips": len(flips_negative),
                "positive_details": [
                    {"task_id": t["task_id"], "benchmark": t["benchmark"],
                     "bl_reward": t.get("baseline_reward"), "mcp_reward": t.get(f"{cfg}_reward")}
                    for t in flips_positive[:10]
                ],
                "negative_details": [
                    {"task_id": t["task_id"], "benchmark": t["benchmark"],
                     "bl_reward": t.get("baseline_reward"), "mcp_reward": t.get(f"{cfg}_reward")}
                    for t in flips_negative[:10]
                ],
            },
            "by_benchmark": {
                bm: {"mean_delta": round(safe_mean(vals), 4), "n": len(vals),
                      "n_improved": sum(1 for d in vals if d > 0.01),
                      "n_degraded": sum(1 for d in vals if d < -0.01)}
                for bm, vals in sorted(by_benchmark.items())
            },
            "by_difficulty": {
                k: {"mean_delta": round(safe_mean(v), 4), "n": len(v)}
                for k, v in sorted(by_difficulty.items())
            },
            "by_sdlc_phase": {
                k: {"mean_delta": round(safe_mean(v), 4), "n": len(v)}
                for k, v in sorted(by_sdlc.items())
            },
            "by_loc_bucket": {
                k: {"mean_delta": round(safe_mean(v), 4), "n": len(v)}
                for k, v in sorted(by_loc_bucket.items())
            },
            "by_files_bucket": {
                k: {"mean_delta": round(safe_mean(v), 4), "n": len(v)}
                for k, v in sorted(by_files_bucket.items())
            },
            "by_mcp_score_bucket": {
                k: {"mean_delta": round(safe_mean(v), 4), "n": len(v)}
                for k, v in sorted(by_mcp_score.items())
            },
        }

    return results


def _token_verification(paired: list[dict]) -> dict:
    """Verify token usage accuracy and consistency."""
    issues = []
    stats = {"total_checks": 0, "has_tokens": 0, "zero_input": 0, "zero_output": 0,
             "suspiciously_low": 0, "suspiciously_high": 0}

    for task in paired:
        for cfg in CONFIGS:
            inp = task.get(f"{cfg}_input_tokens")
            out = task.get(f"{cfg}_output_tokens")
            cache_create = task.get(f"{cfg}_cache_creation_tokens")
            cache_read = task.get(f"{cfg}_cache_read_tokens")

            if inp is None and out is None:
                continue
            stats["total_checks"] += 1
            stats["has_tokens"] += 1

            if inp is not None and inp == 0:
                stats["zero_input"] += 1
            if out is not None and out == 0:
                stats["zero_output"] += 1
                issues.append({
                    "task_id": task["task_id"],
                    "benchmark": task["benchmark"],
                    "config": cfg,
                    "issue": "zero_output_tokens",
                })

            # Check for suspiciously low (possible auth failure / no work done)
            if out is not None and 0 < out < 100:
                stats["suspiciously_low"] += 1
                issues.append({
                    "task_id": task["task_id"],
                    "benchmark": task["benchmark"],
                    "config": cfg,
                    "issue": "very_low_output_tokens",
                    "output_tokens": out,
                })

            # Check for suspiciously high cache reads vs output
            if cache_read and out and cache_read > 0 and out > 0:
                ratio = cache_read / out
                if ratio > 500:
                    stats["suspiciously_high"] += 1

    return {
        "stats": stats,
        "issues": issues[:20],
    }


def _mcp_effectiveness_analysis(paired: list[dict]) -> dict:
    """Analyze whether MCP tools were used effectively: correlation between MCP usage and outcomes."""
    # Bin tasks by MCP ratio and compare outcomes
    bins = [
        (0, 0, "no_mcp (0%)"),
        (0.001, 0.1, "light_mcp (0-10%)"),
        (0.1, 0.3, "moderate_mcp (10-30%)"),
        (0.3, 1.0, "heavy_mcp (30%+)"),
    ]

    results = {}
    for cfg in ["sourcegraph_base", "sourcegraph_full"]:
        prefix = "sg_base" if "base" in cfg else "sg_full"
        bin_results = {}
        for lo, hi, label in bins:
            tasks_in_bin = []
            for task in paired:
                ratio = task.get(f"{cfg}_mcp_ratio")
                if ratio is None:
                    continue
                if lo == 0 and hi == 0 and ratio == 0:
                    tasks_in_bin.append(task)
                elif lo > 0 and lo <= ratio <= hi:
                    tasks_in_bin.append(task)

            if not tasks_in_bin:
                continue

            rewards = [t.get(f"{cfg}_reward", 0) or 0 for t in tasks_in_bin]
            bl_rewards = [t.get("baseline_reward", 0) or 0 for t in tasks_in_bin]
            time_deltas = [t.get(f"{prefix}_time_delta_pct") for t in tasks_in_bin if t.get(f"{prefix}_time_delta_pct") is not None]

            bin_results[label] = {
                "n_tasks": len(tasks_in_bin),
                "mcp_mean_reward": round(safe_mean(rewards), 3) if rewards else None,
                "baseline_mean_reward": round(safe_mean(bl_rewards), 3) if bl_rewards else None,
                "reward_delta": round(safe_mean(rewards) - safe_mean(bl_rewards), 4) if rewards and bl_rewards else None,
                "mean_time_delta_pct": round(safe_mean(time_deltas), 1) if time_deltas else None,
            }

        results[cfg] = bin_results

    # MCP usage correlated with benchmark/task type
    mcp_vs_task_type = defaultdict(lambda: {"mcp_calls": [], "rewards": [], "time_deltas": []})
    for task in paired:
        for cfg in ["sourcegraph_base", "sourcegraph_full"]:
            prefix = "sg_base" if "base" in cfg else "sg_full"
            mcp_calls = task.get(f"{cfg}_tool_calls_mcp")
            reward = task.get(f"{cfg}_reward")
            td = task.get(f"{prefix}_time_delta_pct")
            sdlc = task.get("sdlc_phase", "unknown") or "unknown"

            if mcp_calls is not None:
                key = (sdlc, cfg)
                mcp_vs_task_type[key]["mcp_calls"].append(mcp_calls)
                if reward is not None:
                    mcp_vs_task_type[key]["rewards"].append(reward)
                if td is not None:
                    mcp_vs_task_type[key]["time_deltas"].append(td)

    results["by_sdlc_phase"] = {
        f"{sdlc}/{cfg}": {
            "avg_mcp_calls": round(safe_mean(v["mcp_calls"]), 1) if v["mcp_calls"] else 0,
            "avg_reward": round(safe_mean(v["rewards"]), 3) if v["rewards"] else None,
            "avg_time_delta_pct": round(safe_mean(v["time_deltas"]), 1) if v["time_deltas"] else None,
            "n": len(v["mcp_calls"]),
        }
        for (sdlc, cfg), v in sorted(mcp_vs_task_type.items())
    }

    return results


def format_report(report: dict) -> str:
    """Format the audit report as human-readable text."""
    lines = []
    lines.append("=" * 80)
    lines.append("  MCP USAGE AUDIT REPORT — CodeContextBench")
    lines.append("=" * 80)

    # Summary
    s = report.get("summary", {})
    lines.append(f"\nTotal paired tasks: {s.get('total_paired_tasks', 0)}")
    lines.append(f"Tasks with all 3 configs: {s.get('tasks_with_all_configs', 0)}")
    lines.append(f"Benchmarks: {s.get('n_benchmarks', 0)}")

    # === Section 1: Timing Verification ===
    lines.append("\n" + "=" * 80)
    lines.append("  1. TIMING METHODOLOGY VERIFICATION")
    lines.append("=" * 80)
    tv = report.get("timing_verification", {})
    ts = tv.get("stats", {})
    lines.append(f"  Total task-config pairs checked: {ts.get('total_tasks', 0)}")
    lines.append(f"  Has agent_execution_seconds:     {ts.get('has_agent_time', 0)}")
    lines.append(f"  Has wall_clock_seconds:          {ts.get('has_wall_time', 0)}")
    lines.append(f"  Has environment_setup_seconds:    {ts.get('has_env_setup', 0)}")
    lines.append(f"  Has verifier_seconds:            {ts.get('has_verifier', 0)}")
    lines.append(f"  Timing consistent (agent < wall): {ts.get('timing_consistent', 0)}")
    lines.append(f"  Timing INCONSISTENT:              {ts.get('timing_inconsistent', 0)}")
    if tv.get("issues"):
        lines.append(f"\n  Issues ({len(tv['issues'])} shown):")
        for iss in tv["issues"][:5]:
            lines.append(f"    {iss}")

    # === Section 2: Token Verification ===
    lines.append("\n" + "=" * 80)
    lines.append("  2. TOKEN USAGE VERIFICATION")
    lines.append("=" * 80)
    tok = report.get("token_verification", {})
    tok_s = tok.get("stats", {})
    lines.append(f"  Total checks:        {tok_s.get('total_checks', 0)}")
    lines.append(f"  Has token data:      {tok_s.get('has_tokens', 0)}")
    lines.append(f"  Zero output tokens:  {tok_s.get('zero_output', 0)}")
    lines.append(f"  Suspiciously low:    {tok_s.get('suspiciously_low', 0)}")
    if tok.get("issues"):
        lines.append(f"\n  Issues ({len(tok['issues'])} shown):")
        for iss in tok["issues"][:5]:
            lines.append(f"    {iss}")

    # === Section 3: MCP Usage ===
    lines.append("\n" + "=" * 80)
    lines.append("  3. MCP TOOL USAGE ANALYSIS")
    lines.append("=" * 80)
    mcp = report.get("mcp_usage", {})

    lines.append("\n  Global MCP Tool Usage (all MCP configs combined):")
    for tool, count in (mcp.get("mcp_tool_totals", {}) or {}).items():
        lines.append(f"    {tool:30s} {count:>6d}")

    sv = mcp.get("search_vs_navigation", {})
    lines.append(f"\n  Search calls: {sv.get('search', 0)}  |  Navigation calls: {sv.get('navigation', 0)}")

    lines.append("\n  MCP Ratio Stats by Config:")
    for cfg, stats in (mcp.get("mcp_ratio_stats", {}) or {}).items():
        lines.append(f"    {cfg}: mean={stats.get('mean')}, median={stats.get('median')}, "
                     f"max={stats.get('max')}, zero_mcp={stats.get('n_zero')}/{stats.get('n_tasks')}")

    lines.append("\n  Per-Benchmark MCP Adoption:")
    lines.append(f"    {'Benchmark/Config':50s} {'Tasks':>5s} {'w/MCP':>5s} {'Adopt%':>6s} {'AvgCalls':>8s}")
    for key, val in sorted((mcp.get("per_benchmark", {}) or {}).items()):
        lines.append(f"    {key:50s} {val['tasks_total']:>5d} {val['tasks_with_mcp']:>5d} "
                     f"{val['adoption_rate']*100:>5.1f}% {val['avg_mcp_calls']:>7.1f}")

    # === Section 4: Reward Analysis ===
    lines.append("\n" + "=" * 80)
    lines.append("  4. REWARD ANALYSIS (MCP vs Baseline)")
    lines.append("=" * 80)
    rew = report.get("reward_analysis", {})

    for prefix in ["sg_base", "sg_full"]:
        pdata = rew.get(prefix, {})
        overall = pdata.get("overall", {})
        lines.append(f"\n  --- {prefix.upper()} vs BASELINE ---")
        lines.append(f"  Mean reward delta:   {overall.get('mean_delta')}")
        lines.append(f"  Median reward delta: {overall.get('median_delta')}")
        lines.append(f"  Improved: {overall.get('n_improved', 0)}  |  Neutral: {overall.get('n_neutral', 0)}  |  Degraded: {overall.get('n_degraded', 0)}  |  Total: {overall.get('n_total', 0)}")

        flips = pdata.get("flips", {})
        lines.append(f"  Positive flips (BL fail -> MCP pass): {flips.get('positive_flips', 0)}")
        for f in flips.get("positive_details", [])[:5]:
            lines.append(f"    + {f['task_id']} ({f['benchmark']}): {f['bl_reward']} -> {f['mcp_reward']}")
        lines.append(f"  Negative flips (BL pass -> MCP fail): {flips.get('negative_flips', 0)}")
        for f in flips.get("negative_details", [])[:5]:
            lines.append(f"    - {f['task_id']} ({f['benchmark']}): {f['bl_reward']} -> {f['mcp_reward']}")

        lines.append(f"\n  By Benchmark:")
        lines.append(f"    {'Benchmark':30s} {'MeanDelta':>10s} {'N':>4s} {'Improved':>8s} {'Degraded':>8s}")
        for bm, bv in sorted(pdata.get("by_benchmark", {}).items()):
            lines.append(f"    {bm:30s} {bv['mean_delta']:>+10.4f} {bv['n']:>4d} {bv.get('n_improved',0):>8d} {bv.get('n_degraded',0):>8d}")

        lines.append(f"\n  By Difficulty:")
        for k, v in sorted(pdata.get("by_difficulty", {}).items()):
            lines.append(f"    {k:20s} delta={v['mean_delta']:>+.4f}  n={v['n']}")

        lines.append(f"\n  By SDLC Phase:")
        for k, v in sorted(pdata.get("by_sdlc_phase", {}).items()):
            lines.append(f"    {k:35s} delta={v['mean_delta']:>+.4f}  n={v['n']}")

        lines.append(f"\n  By Code Complexity (LOC changed):")
        for k, v in sorted(pdata.get("by_loc_bucket", {}).items()):
            lines.append(f"    {k:25s} delta={v['mean_delta']:>+.4f}  n={v['n']}")

        lines.append(f"\n  By Files Modified:")
        for k, v in sorted(pdata.get("by_files_bucket", {}).items()):
            lines.append(f"    {k:25s} delta={v['mean_delta']:>+.4f}  n={v['n']}")

        lines.append(f"\n  By MCP Predicted Benefit Score:")
        for k, v in sorted(pdata.get("by_mcp_score_bucket", {}).items()):
            lines.append(f"    {k:25s} delta={v['mean_delta']:>+.4f}  n={v['n']}")

    # === Section 5: Efficiency ===
    lines.append("\n" + "=" * 80)
    lines.append("  5. EFFICIENCY ANALYSIS (Agent Task Time)")
    lines.append("=" * 80)
    eff = report.get("efficiency", {})

    for prefix in ["sg_base", "sg_full"]:
        pdata = eff.get(prefix, {})
        td = pdata.get("time_delta_pct", {})
        cd = pdata.get("cost_delta_pct", {})
        od = pdata.get("output_tokens_delta_pct", {})

        lines.append(f"\n  --- {prefix.upper()} vs BASELINE ---")
        lines.append(f"  Task Time Delta:  mean={td.get('mean')}%  trimmed_mean={td.get('trimmed_mean')}%  median={td.get('median')}%")
        lines.append(f"    Faster (<-5%): {td.get('n_faster', 0)}  |  Neutral: {td.get('n_neutral', 0)}  |  Slower (>+5%): {td.get('n_slower', 0)}  |  Total: {td.get('n_total', 0)}")
        lines.append(f"  Cost Delta:       mean={cd.get('mean')}%  trimmed_mean={cd.get('trimmed_mean')}%  median={cd.get('median')}%")
        lines.append(f"  Output Tokens:    mean={od.get('mean')}%  trimmed_mean={od.get('trimmed_mean')}%  median={od.get('median')}%")

        lines.append(f"\n  By Benchmark (Task Time Delta %):")
        lines.append(f"    {'Benchmark':30s} {'TrimMean%':>10s} {'Med%':>8s} {'N':>4s} {'Faster':>6s} {'Slower':>6s}")
        for bm, bv in sorted(pdata.get("time_by_benchmark", {}).items()):
            lines.append(f"    {bm:30s} {bv.get('trimmed_mean_pct', bv['mean_delta_pct']):>+9.1f}% {bv['median_delta_pct']:>+7.1f}% {bv['n_tasks']:>4d} {bv['n_faster']:>6d} {bv['n_slower']:>6d}")

    # === Section 6: MCP Effectiveness ===
    lines.append("\n" + "=" * 80)
    lines.append("  6. MCP EFFECTIVENESS (Usage vs Outcome)")
    lines.append("=" * 80)
    eff_data = report.get("mcp_effectiveness", {})

    for cfg in ["sourcegraph_base", "sourcegraph_full"]:
        bins = eff_data.get(cfg, {})
        if not bins:
            continue
        lines.append(f"\n  --- {cfg} ---")
        lines.append(f"    {'MCP Usage Bin':25s} {'N':>4s} {'MCPReward':>10s} {'BLReward':>10s} {'RewDelta':>10s} {'TimeDelta%':>10s}")
        for label, bv in bins.items():
            lines.append(f"    {label:25s} {bv['n_tasks']:>4d} "
                         f"{bv['mcp_mean_reward'] or 0:>10.3f} {bv['baseline_mean_reward'] or 0:>10.3f} "
                         f"{bv['reward_delta'] or 0:>+10.4f} {bv['mean_time_delta_pct'] or 0:>+9.1f}%")

    lines.append(f"\n  MCP Effectiveness by SDLC Phase:")
    sdlc_data = eff_data.get("by_sdlc_phase", {})
    lines.append(f"    {'Phase/Config':50s} {'AvgMCP':>7s} {'Reward':>7s} {'Time%':>8s} {'N':>4s}")
    for key, val in sorted(sdlc_data.items()):
        lines.append(f"    {key:50s} {val['avg_mcp_calls']:>6.1f} "
                     f"{val['avg_reward'] or 0:>7.3f} {val['avg_time_delta_pct'] or 0:>+7.1f}% {val['n']:>4d}")

    lines.append("\n" + "=" * 80)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="MCP Usage Audit for CodeContextBench")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--verbose", action="store_true", help="Include per-task details")
    parser.add_argument("--output", type=str, help="Write report to file")
    parser.add_argument("--paired-only", action="store_true", default=True,
                       help="Only analyze paired_rerun_* batches (default: True)")
    parser.add_argument("--all-runs", action="store_true",
                       help="Analyze ALL run batches, not just paired reruns")
    args = parser.parse_args()

    paired_only = not args.all_runs

    print(f"Collecting task metrics (paired_only={paired_only})...", file=sys.stderr)
    all_metrics = collect_task_metrics(paired_only=paired_only)
    print(f"  Found {len(all_metrics)} task-config records", file=sys.stderr)

    print("Loading selection metadata...", file=sys.stderr)
    selection_meta = load_selection_metadata()
    print(f"  {len(selection_meta)} tasks in selection registry", file=sys.stderr)

    # Filter out auth failures / broken runs
    valid_metrics = [m for m in all_metrics if _is_valid_task(m)]
    invalid_count = len(all_metrics) - len(valid_metrics)
    print(f"  Filtered {invalid_count} invalid tasks (auth failures, zero output)", file=sys.stderr)
    print(f"  {len(valid_metrics)} valid task-config records", file=sys.stderr)

    print("Building paired analysis...", file=sys.stderr)
    paired = build_paired_analysis(valid_metrics, selection_meta)
    print(f"  {len(paired)} unique tasks", file=sys.stderr)

    # Count completeness
    all3 = sum(1 for t in paired
               if t.get("baseline_reward") is not None
               and t.get("sourcegraph_base_reward") is not None
               and t.get("sourcegraph_full_reward") is not None)

    benchmarks = set(t.get("benchmark", "") for t in paired)

    report = {
        "summary": {
            "total_paired_tasks": len(paired),
            "tasks_with_all_configs": all3,
            "n_benchmarks": len(benchmarks),
            "benchmarks": sorted(benchmarks),
        },
        "timing_verification": _timing_verification(paired),
        "token_verification": _token_verification(paired),
        "mcp_usage": _mcp_usage_analysis(paired),
        "reward_analysis": _reward_analysis(paired),
        "efficiency": _efficiency_analysis(paired),
        "mcp_effectiveness": _mcp_effectiveness_analysis(paired),
    }

    if args.verbose:
        report["per_task"] = paired

    if args.json:
        output = json.dumps(report, indent=2, default=str)
    else:
        output = format_report(report)

    if args.output:
        Path(args.output).write_text(output)
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
