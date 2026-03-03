#!/usr/bin/env python3
"""Extract multi-run averaged data for V2 technical report sections.

Scans runs/official/ for task-level result.json and task_metrics.json,
normalizes task names, pairs baseline/MCP, averages across runs,
and produces breakdowns by language, difficulty, codebase size, timing, cost, tool usage.
"""

import json
import glob
import re
import os
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parent.parent
OFFICIAL = ROOT / "runs" / "official"
TASKS_FILE = ROOT / "configs" / "selected_benchmark_tasks.json"

# Load task metadata - convert list to dict keyed by task_id (lowercased)
with open(TASKS_FILE) as f:
    _tasks_raw = json.load(f)["tasks"]
    if isinstance(_tasks_raw, list):
        TASK_META = {t["task_id"].lower(): t for t in _tasks_raw}
    else:
        TASK_META = {k.lower(): v for k, v in _tasks_raw.items()}

# Build canonical sets
SDLC_TASKS = set()
ORG_TASKS = set()
for tid, meta in TASK_META.items():
    bm = meta.get("benchmark", "")
    if "sdlc" in bm or (bm.startswith("ccb_") and not bm.startswith("ccb_mcp_")):
        SDLC_TASKS.add(tid)
    else:
        ORG_TASKS.add(tid)


# Merged suite mapping (reporting-layer only, original suites preserved)
# See docs/analysis/suite_merge_analysis.md for rationale
SUITE_MERGE_MAP = {
    "csb_org_crossorg": "crossorg_merged",
    "csb_org_org": "crossorg_merged",
    "csb_org_compliance": "compliance_platform",
    "csb_org_platform": "compliance_platform",
}


def get_merged_suite(benchmark: str) -> str:
    """Map a benchmark suite to its merged name, or return original."""
    return SUITE_MERGE_MAP.get(benchmark, benchmark)


def normalize_task_name(raw_name: str) -> str:
    """Strip Harbor prefixes/suffixes to get canonical task name."""
    name = raw_name
    # Strip mcp_ prefix
    name = re.sub(r"^mcp_", "", name, flags=re.IGNORECASE)
    # Strip bl_ prefix
    name = re.sub(r"^bl_", "", name, flags=re.IGNORECASE)
    # Strip sgonly_ prefix
    name = re.sub(r"^sgonly_", "", name, flags=re.IGNORECASE)
    # Strip Harbor random suffix: _XXXXXX or _XXXXXXX (6-8 alphanumeric)
    name = re.sub(r"_[A-Za-z0-9]{6,8}$", "", name)
    # Lowercase for case-insensitive matching
    name = name.lower()
    return name


def classify_config(config_name: str) -> str:
    """Classify config as 'baseline' or 'mcp'."""
    if "baseline" in config_name:
        return "baseline"
    elif "mcp" in config_name:
        return "mcp"
    return "unknown"


def get_suite_type_for_task(task_name: str) -> str:
    """Classify task as 'sdlc' or 'org' using canonical metadata."""
    if task_name in SDLC_TASKS:
        return "sdlc"
    elif task_name in ORG_TASKS:
        return "org"
    return "unknown"


def parse_timestamp(ts: str) -> datetime:
    """Parse ISO timestamp."""
    # Handle both Z and +00:00 formats
    ts = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts)
    except:
        return None


def find_task_metadata(task_name: str) -> dict:
    """Find task metadata from selected_benchmark_tasks.json."""
    # Direct lookup (already lowercase from normalize_task_name)
    if task_name in TASK_META:
        return TASK_META[task_name]
    # Case-insensitive lookup
    task_lower = task_name.lower()
    for k, v in TASK_META.items():
        if k.lower() == task_lower:
            return v
    return {}


def _process_task_dir(task_dir, run_name, config_type, records):
    """Extract a task record from a directory containing result.json."""
    result_file = task_dir / "result.json"
    if not result_file.exists():
        return

    try:
        with open(result_file) as f:
            result = json.load(f)
    except (json.JSONDecodeError, IOError):
        return

    # Skip batch-level result.json (has 'stats' key, no 'agent_result')
    if "stats" in result and "agent_result" not in result:
        return

    # Extract reward - check both top-level and nested verifier_result
    agent_result = result.get("agent_result") or {}
    vr = result.get("verifier_result") or agent_result.get("verifier_result") or {}
    rewards = vr.get("rewards") or {}
    reward = rewards.get("reward")
    if reward is None:
        return

    # Normalize task name
    raw_name = result.get("task_name", task_dir.name)
    raw_name = re.sub(r"__[A-Za-z0-9]+$", "", raw_name)
    task_name = normalize_task_name(raw_name)

    # Skip non-canonical tasks
    if task_name not in TASK_META:
        return

    suite_type = get_suite_type_for_task(task_name)

    n_input = agent_result.get("n_input_tokens", 0) or 0
    n_output = agent_result.get("n_output_tokens", 0) or 0
    n_cache = agent_result.get("n_cache_tokens", 0) or 0
    cost = agent_result.get("cost_usd")

    wall_clock = None
    started = result.get("started_at")
    finished = result.get("finished_at")
    if started and finished:
        t_start = parse_timestamp(started)
        t_end = parse_timestamp(finished)
        if t_start and t_end:
            wall_clock = (t_end - t_start).total_seconds()

    agent_exec_seconds = None
    agent_exec = result.get("agent_execution")
    if isinstance(agent_exec, dict) and agent_exec.get("started_at") and agent_exec.get("finished_at"):
        t_s = parse_timestamp(agent_exec["started_at"])
        t_e = parse_timestamp(agent_exec["finished_at"])
        if t_s and t_e:
            agent_exec_seconds = (t_e - t_s).total_seconds()

    rec = {
        "task_name": task_name,
        "run_name": run_name,
        "config_type": config_type,
        "suite_type": suite_type,
        "reward": reward,
        "input_tokens": n_input,
        "output_tokens": n_output,
        "cache_tokens": n_cache,
        "cost_usd": cost,
        "wall_clock_seconds": wall_clock,
        "agent_execution_seconds": agent_exec_seconds,
    }

    # Try to load task_metrics.json for richer data
    metrics_file = task_dir / "task_metrics.json"
    if metrics_file.exists():
        try:
            with open(metrics_file) as f:
                metrics = json.load(f)
            if metrics.get("agent_execution_seconds") is not None:
                rec["agent_execution_seconds"] = metrics["agent_execution_seconds"]
            rec["tool_calls_total"] = metrics.get("tool_calls_total")
            rec["tool_calls_mcp"] = metrics.get("tool_calls_mcp")
            rec["tool_calls_local"] = metrics.get("tool_calls_local")
            rec["mcp_ratio"] = metrics.get("mcp_ratio")
            rec["search_calls_keyword"] = metrics.get("search_calls_keyword")
            rec["search_calls_nls"] = metrics.get("search_calls_nls")
            rec["search_calls_deepsearch"] = metrics.get("search_calls_deepsearch")
            rec["search_strategy_type"] = metrics.get("search_strategy_type")
            rec["conversation_turns"] = metrics.get("conversation_turns")
            if metrics.get("cost_usd") is not None:
                rec["cost_usd"] = metrics["cost_usd"]
            if metrics.get("input_tokens") is not None:
                rec["input_tokens"] = metrics["input_tokens"]
            if metrics.get("output_tokens") is not None:
                rec["output_tokens"] = metrics["output_tokens"]
        except:
            pass

    # Add task metadata
    meta = find_task_metadata(task_name)
    rec["language"] = meta.get("language", "unknown")
    rec["difficulty"] = meta.get("difficulty", "unknown")
    rec["task_context_length"] = meta.get("context_length")
    rec["task_files_count"] = meta.get("files_count")

    records.append(rec)


def scan_all_tasks():
    """Scan all task-level results from runs/official/.

    Handles both directory formats:
    - New format: run_dir/config_dir/YYYY-MM-DD__HH-MM-SS/task_dir/result.json
    - Old format: run_dir/config_dir/ccb_*_batch_dir/task_dir/result.json
    """
    records = []

    for run_dir in sorted(OFFICIAL.iterdir()):
        if not run_dir.is_dir() or run_dir.name == "archive":
            continue
        run_name = run_dir.name

        for config_dir in sorted(run_dir.iterdir()):
            if not config_dir.is_dir():
                continue
            config_name = config_dir.name
            config_type = classify_config(config_name)
            if config_type == "unknown":
                continue

            for sub_dir in sorted(config_dir.iterdir()):
                if not sub_dir.is_dir():
                    continue

                # New format: timestamp directories
                if re.match(r"^\d{4}-\d{2}-\d{2}", sub_dir.name):
                    for task_dir in sorted(sub_dir.iterdir()):
                        if not task_dir.is_dir():
                            continue
                        _process_task_dir(task_dir, run_name, config_type, records)

                # Old format: batch directories (ccb_* or csb_*)
                elif sub_dir.name.startswith(("ccb_", "csb_")):
                    for task_dir in sorted(sub_dir.iterdir()):
                        if not task_dir.is_dir():
                            continue
                        _process_task_dir(task_dir, run_name, config_type, records)

    return records


def compute_paired_stats(records):
    """Group by task, average across runs per config, compute paired deltas."""
    # Group: task_name -> config_type -> list of records
    grouped = defaultdict(lambda: defaultdict(list))
    for r in records:
        grouped[r["task_name"]][r["config_type"]].append(r)

    paired = []
    for task_name, by_config in grouped.items():
        if "baseline" not in by_config or "mcp" not in by_config:
            continue

        bl_records = by_config["baseline"]
        mcp_records = by_config["mcp"]

        # Average rewards across runs
        bl_mean = statistics.mean(r["reward"] for r in bl_records)
        mcp_mean = statistics.mean(r["reward"] for r in mcp_records)

        # Get metadata from first record
        meta = bl_records[0]

        # Average other metrics where available
        def avg_field(records, field):
            vals = [r[field] for r in records if r.get(field) is not None]
            return statistics.mean(vals) if vals else None

        # Get benchmark suite from task metadata
        task_meta = find_task_metadata(task_name)
        benchmark = task_meta.get("benchmark", "unknown")
        merged_suite = get_merged_suite(benchmark)

        paired.append({
            "task_name": task_name,
            "language": meta["language"],
            "difficulty": meta["difficulty"],
            "suite_type": meta["suite_type"],
            "benchmark": benchmark,
            "merged_suite": merged_suite,
            "task_context_length": meta.get("task_context_length"),
            "task_files_count": meta.get("task_files_count"),
            "bl_reward": bl_mean,
            "mcp_reward": mcp_mean,
            "delta": mcp_mean - bl_mean,
            "n_bl_runs": len(bl_records),
            "n_mcp_runs": len(mcp_records),
            # Timing/cost averages
            "bl_wall_clock": avg_field(bl_records, "wall_clock_seconds"),
            "mcp_wall_clock": avg_field(mcp_records, "wall_clock_seconds"),
            "bl_agent_exec": avg_field(bl_records, "agent_execution_seconds"),
            "mcp_agent_exec": avg_field(mcp_records, "agent_execution_seconds"),
            "bl_cost": avg_field(bl_records, "cost_usd"),
            "mcp_cost": avg_field(mcp_records, "cost_usd"),
            "bl_input_tokens": avg_field(bl_records, "input_tokens"),
            "mcp_input_tokens": avg_field(mcp_records, "input_tokens"),
            "bl_output_tokens": avg_field(bl_records, "output_tokens"),
            "mcp_output_tokens": avg_field(mcp_records, "output_tokens"),
            # MCP tool usage (MCP config only)
            "mcp_tool_calls_total": avg_field(mcp_records, "tool_calls_total"),
            "mcp_tool_calls_mcp": avg_field(mcp_records, "tool_calls_mcp"),
            "mcp_tool_calls_local": avg_field(mcp_records, "tool_calls_local"),
            "mcp_mcp_ratio": avg_field(mcp_records, "mcp_ratio"),
            "bl_tool_calls_total": avg_field(bl_records, "tool_calls_total"),
            "mcp_search_keyword": avg_field(mcp_records, "search_calls_keyword"),
            "mcp_search_nls": avg_field(mcp_records, "search_calls_nls"),
            "mcp_search_deepsearch": avg_field(mcp_records, "search_calls_deepsearch"),
            "bl_conversation_turns": avg_field(bl_records, "conversation_turns"),
            "mcp_conversation_turns": avg_field(mcp_records, "conversation_turns"),
        })

    return paired


def breakdown_by(paired, field, min_n=3):
    """Compute reward stats grouped by a field."""
    groups = defaultdict(list)
    for p in paired:
        val = p.get(field, "unknown")
        if val is None:
            val = "unknown"
        groups[val].append(p)

    results = {}
    for val, tasks in sorted(groups.items(), key=lambda x: -len(x[1])):
        n = len(tasks)
        bl_mean = statistics.mean(t["bl_reward"] for t in tasks)
        mcp_mean = statistics.mean(t["mcp_reward"] for t in tasks)
        delta = mcp_mean - bl_mean

        # Win/loss/neutral
        wins = sum(1 for t in tasks if t["delta"] > 0.01)
        losses = sum(1 for t in tasks if t["delta"] < -0.01)
        neutral = n - wins - losses

        results[val] = {
            "n": n,
            "bl_mean": round(bl_mean, 3),
            "mcp_mean": round(mcp_mean, 3),
            "delta": round(delta, 3),
            "wins": wins,
            "losses": losses,
            "neutral": neutral,
        }

    return results


def breakdown_by_bins(paired, field, bins, labels):
    """Compute reward stats for binned numeric field."""
    groups = defaultdict(list)
    for p in paired:
        val = p.get(field)
        if val is None:
            groups["unknown"].append(p)
            continue
        for i, threshold in enumerate(bins):
            if val < threshold:
                groups[labels[i]].append(p)
                break
        else:
            groups[labels[-1]].append(p)

    results = {}
    for label in labels + ["unknown"]:
        tasks = groups.get(label, [])
        if not tasks:
            continue
        n = len(tasks)
        bl_mean = statistics.mean(t["bl_reward"] for t in tasks)
        mcp_mean = statistics.mean(t["mcp_reward"] for t in tasks)
        delta = mcp_mean - bl_mean
        results[label] = {
            "n": n,
            "bl_mean": round(bl_mean, 3),
            "mcp_mean": round(mcp_mean, 3),
            "delta": round(delta, 3),
        }

    return results


def compute_timing_stats(paired):
    """Compute timing statistics across paired tasks."""
    # Wall clock
    wc_bl = [p["bl_wall_clock"] for p in paired if p["bl_wall_clock"] is not None]
    wc_mcp = [p["mcp_wall_clock"] for p in paired if p["mcp_wall_clock"] is not None]

    # Agent execution
    ae_bl = [p["bl_agent_exec"] for p in paired if p["bl_agent_exec"] is not None]
    ae_mcp = [p["mcp_agent_exec"] for p in paired if p["mcp_agent_exec"] is not None]

    # Paired wall clock deltas
    wc_paired = [(p["mcp_wall_clock"], p["bl_wall_clock"])
                  for p in paired
                  if p["bl_wall_clock"] is not None and p["mcp_wall_clock"] is not None]

    return {
        "wall_clock": {
            "n_bl": len(wc_bl),
            "n_mcp": len(wc_mcp),
            "bl_mean": round(statistics.mean(wc_bl), 1) if wc_bl else None,
            "mcp_mean": round(statistics.mean(wc_mcp), 1) if wc_mcp else None,
            "bl_median": round(statistics.median(wc_bl), 1) if wc_bl else None,
            "mcp_median": round(statistics.median(wc_mcp), 1) if wc_mcp else None,
            "n_paired": len(wc_paired),
            "mean_delta": round(statistics.mean(m - b for m, b in wc_paired), 1) if wc_paired else None,
        },
        "agent_execution": {
            "n_bl": len(ae_bl),
            "n_mcp": len(ae_mcp),
            "bl_mean": round(statistics.mean(ae_bl), 1) if ae_bl else None,
            "mcp_mean": round(statistics.mean(ae_mcp), 1) if ae_mcp else None,
            "bl_median": round(statistics.median(ae_bl), 1) if ae_bl else None,
            "mcp_median": round(statistics.median(ae_mcp), 1) if ae_mcp else None,
        }
    }


def compute_cost_stats(paired):
    """Compute cost statistics."""
    cost_bl = [p["bl_cost"] for p in paired if p["bl_cost"] is not None]
    cost_mcp = [p["mcp_cost"] for p in paired if p["mcp_cost"] is not None]

    paired_costs = [(p["bl_cost"], p["mcp_cost"])
                     for p in paired
                     if p["bl_cost"] is not None and p["mcp_cost"] is not None]

    return {
        "n_bl": len(cost_bl),
        "n_mcp": len(cost_mcp),
        "bl_mean": round(statistics.mean(cost_bl), 4) if cost_bl else None,
        "mcp_mean": round(statistics.mean(cost_mcp), 4) if cost_mcp else None,
        "bl_median": round(statistics.median(cost_bl), 4) if cost_bl else None,
        "mcp_median": round(statistics.median(cost_mcp), 4) if cost_mcp else None,
        "bl_total": round(sum(cost_bl), 2) if cost_bl else None,
        "mcp_total": round(sum(cost_mcp), 2) if cost_mcp else None,
        "n_paired": len(paired_costs),
        "mean_delta": round(statistics.mean(m - b for b, m in paired_costs), 4) if paired_costs else None,
    }


def compute_tool_usage_stats(paired):
    """Compute MCP tool usage statistics."""
    mcp_tasks = [p for p in paired if p["mcp_tool_calls_total"] is not None]

    if not mcp_tasks:
        return {"n": 0, "message": "No tool usage data available"}

    total_calls = [p["mcp_tool_calls_total"] for p in mcp_tasks]
    mcp_calls = [p["mcp_tool_calls_mcp"] for p in mcp_tasks if p["mcp_tool_calls_mcp"] is not None]
    local_calls = [p["mcp_tool_calls_local"] for p in mcp_tasks if p["mcp_tool_calls_local"] is not None]
    mcp_ratios = [p["mcp_mcp_ratio"] for p in mcp_tasks if p["mcp_mcp_ratio"] is not None]

    # Search patterns
    kw = [p["mcp_search_keyword"] for p in mcp_tasks if p["mcp_search_keyword"] is not None]
    nls = [p["mcp_search_nls"] for p in mcp_tasks if p["mcp_search_nls"] is not None]
    ds = [p["mcp_search_deepsearch"] for p in mcp_tasks if p["mcp_search_deepsearch"] is not None]

    # Zero-MCP tasks
    zero_mcp = sum(1 for p in mcp_tasks if p["mcp_tool_calls_mcp"] is not None and p["mcp_tool_calls_mcp"] == 0)

    return {
        "n": len(mcp_tasks),
        "mean_total_calls": round(statistics.mean(total_calls), 1),
        "mean_mcp_calls": round(statistics.mean(mcp_calls), 1) if mcp_calls else None,
        "mean_local_calls": round(statistics.mean(local_calls), 1) if local_calls else None,
        "mean_mcp_ratio": round(statistics.mean(mcp_ratios), 3) if mcp_ratios else None,
        "zero_mcp_tasks": zero_mcp,
        "zero_mcp_pct": round(100 * zero_mcp / len(mcp_tasks), 1) if mcp_tasks else 0,
        "search": {
            "n": len(kw),
            "mean_keyword": round(statistics.mean(kw), 1) if kw else None,
            "mean_nls": round(statistics.mean(nls), 1) if nls else None,
            "mean_deepsearch": round(statistics.mean(ds), 1) if ds else None,
        }
    }


def compute_timing_by_suite(paired):
    """Compute timing by suite type (SDLC vs Org)."""
    results = {}
    for suite_type in ["sdlc", "org"]:
        tasks = [p for p in paired if p["suite_type"] == suite_type]
        wc_paired = [(p["bl_wall_clock"], p["mcp_wall_clock"])
                      for p in tasks
                      if p["bl_wall_clock"] is not None and p["mcp_wall_clock"] is not None]
        cost_paired = [(p["bl_cost"], p["mcp_cost"])
                        for p in tasks
                        if p["bl_cost"] is not None and p["mcp_cost"] is not None]

        results[suite_type] = {
            "n_timing": len(wc_paired),
            "bl_wall_mean": round(statistics.mean(b for b, _ in wc_paired), 1) if wc_paired else None,
            "mcp_wall_mean": round(statistics.mean(m for _, m in wc_paired), 1) if wc_paired else None,
            "wall_delta": round(statistics.mean(m - b for b, m in wc_paired), 1) if wc_paired else None,
            "n_cost": len(cost_paired),
            "bl_cost_mean": round(statistics.mean(b for b, _ in cost_paired), 4) if cost_paired else None,
            "mcp_cost_mean": round(statistics.mean(m for _, m in cost_paired), 4) if cost_paired else None,
            "cost_delta": round(statistics.mean(m - b for b, m in cost_paired), 4) if cost_paired else None,
        }
    return results


def main():
    print("Scanning runs/official/ for task results...", file=sys.stderr)
    records = scan_all_tasks()
    print(f"  Found {len(records)} task evaluations", file=sys.stderr)

    bl_count = sum(1 for r in records if r["config_type"] == "baseline")
    mcp_count = sum(1 for r in records if r["config_type"] == "mcp")
    print(f"  Baseline: {bl_count}, MCP: {mcp_count}", file=sys.stderr)

    print("\nComputing paired statistics...", file=sys.stderr)
    paired = compute_paired_stats(records)
    print(f"  Paired tasks (canonical, any valid eval): {len(paired)}", file=sys.stderr)

    sdlc_paired = [p for p in paired if p["suite_type"] == "sdlc"]
    org_paired = [p for p in paired if p["suite_type"] == "org"]
    print(f"  SDLC: {len(sdlc_paired)}, Org: {len(org_paired)}", file=sys.stderr)

    # Overall stats
    overall_delta = statistics.mean(p["delta"] for p in paired)
    overall_bl = statistics.mean(p["bl_reward"] for p in paired)
    overall_mcp = statistics.mean(p["mcp_reward"] for p in paired)
    print(f"  Overall: BL={overall_bl:.3f}, MCP={overall_mcp:.3f}, delta={overall_delta:+.3f}", file=sys.stderr)

    # Use all paired for sub-analyses (more coverage)
    print("\n=== REWARD BY LANGUAGE ===")
    lang_stats = breakdown_by(paired, "language")
    print(json.dumps(lang_stats, indent=2))

    print("\n=== REWARD BY DIFFICULTY ===")
    diff_stats = breakdown_by(paired, "difficulty")
    print(json.dumps(diff_stats, indent=2))

    print("\n=== REWARD BY SUITE TYPE ===")
    suite_stats = breakdown_by(paired, "suite_type")
    print(json.dumps(suite_stats, indent=2))

    print("\n=== REWARD BY BENCHMARK SUITE ===")
    bench_stats = breakdown_by(paired, "benchmark")
    print(json.dumps(bench_stats, indent=2))

    print("\n=== REWARD BY MERGED SUITE ===")
    merged_stats = breakdown_by(paired, "merged_suite")
    print(json.dumps(merged_stats, indent=2))

    print("\n=== REWARD BY CODEBASE SIZE (Context Length) ===")
    ctx_stats = breakdown_by_bins(
        paired, "task_context_length",
        bins=[100_000, 1_000_000],
        labels=["<100K tokens", "100K--1M tokens", ">1M tokens"]
    )
    print(json.dumps(ctx_stats, indent=2))

    print("\n=== REWARD BY FILES COUNT ===")
    files_stats = breakdown_by_bins(
        paired, "task_files_count",
        bins=[10, 100],
        labels=["<10 files", "10--100 files", ">100 files"]
    )
    print(json.dumps(files_stats, indent=2))

    print("\n=== TIMING ANALYSIS ===")
    timing = compute_timing_stats(paired)
    print(json.dumps(timing, indent=2))

    print("\n=== TIMING BY SUITE TYPE ===")
    timing_suite = compute_timing_by_suite(paired)
    print(json.dumps(timing_suite, indent=2))

    print("\n=== COST ANALYSIS ===")
    cost = compute_cost_stats(paired)
    print(json.dumps(cost, indent=2))

    print("\n=== TOOL USAGE ANALYSIS ===")
    tool = compute_tool_usage_stats(paired)
    print(json.dumps(tool, indent=2))

    # Also compute stats for ALL paired (not just 3+) for operational/aggregate sections
    print("\n=== ALL PAIRED (any run count) ===")
    print(f"n={len(paired)}")
    if paired:
        all_bl = statistics.mean(p["bl_reward"] for p in paired)
        all_mcp = statistics.mean(p["mcp_reward"] for p in paired)
        print(f"BL={all_bl:.3f}, MCP={all_mcp:.3f}, delta={all_mcp-all_bl:+.3f}")

    # Cost by language (for the cost section)
    print("\n=== COST BY LANGUAGE ===")
    cost_by_lang = defaultdict(lambda: {"bl": [], "mcp": []})
    for p in paired:
        if p["bl_cost"] is not None:
            cost_by_lang[p["language"]]["bl"].append(p["bl_cost"])
        if p["mcp_cost"] is not None:
            cost_by_lang[p["language"]]["mcp"].append(p["mcp_cost"])
    for lang, data in sorted(cost_by_lang.items(), key=lambda x: -len(x[1]["bl"])):
        bl_mean = statistics.mean(data["bl"]) if data["bl"] else 0
        mcp_mean = statistics.mean(data["mcp"]) if data["mcp"] else 0
        print(f"  {lang}: n_bl={len(data['bl'])}, n_mcp={len(data['mcp'])}, "
              f"bl=${bl_mean:.4f}, mcp=${mcp_mean:.4f}, delta=${mcp_mean-bl_mean:+.4f}")

    # Wall clock by language
    print("\n=== WALL CLOCK BY LANGUAGE ===")
    wc_by_lang = defaultdict(lambda: {"bl": [], "mcp": []})
    for p in paired:
        if p["bl_wall_clock"] is not None:
            wc_by_lang[p["language"]]["bl"].append(p["bl_wall_clock"])
        if p["mcp_wall_clock"] is not None:
            wc_by_lang[p["language"]]["mcp"].append(p["mcp_wall_clock"])
    for lang, data in sorted(wc_by_lang.items(), key=lambda x: -len(x[1]["bl"])):
        bl_mean = statistics.mean(data["bl"]) if data["bl"] else 0
        mcp_mean = statistics.mean(data["mcp"]) if data["mcp"] else 0
        print(f"  {lang}: n_bl={len(data['bl'])}, n_mcp={len(data['mcp'])}, "
              f"bl={bl_mean:.1f}s, mcp={mcp_mean:.1f}s, delta={mcp_mean-bl_mean:+.1f}s")


if __name__ == "__main__":
    main()
