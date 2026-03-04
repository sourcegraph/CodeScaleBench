#!/usr/bin/env python3
"""Generate a comprehensive evaluation report from Harbor run data.

Discovers all runs in a Harbor official runs directory, extracts metrics,
and produces:
  - eval_report.json  (full structured data)
  - REPORT.md         (human-readable markdown tables)
  - CSV files         (one per table, for downstream analysis)

Stdlib only. Compatible with Python 3.10+.

Usage:
    python3 scripts/generate_eval_report.py \
        --runs-dir ./runs/official/ \
        --output-dir ./eval_reports/
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Optional

# Ensure the repo root is importable
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from csb_metrics import discover_runs, collect_retrieval_data, EvalReport, RunMetrics
from csb_metrics.task_selection import (
    load_selected_tasks,
    build_task_index,
    enrich_runs,
    filter_runs_to_selected,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_mean(values: list) -> Optional[float]:
    """Mean of non-None numeric values, or None."""
    filtered = [v for v in values if v is not None]
    return mean(filtered) if filtered else None


def _fmt(val: Optional[float], decimals: int = 3) -> str:
    """Format a float for display, or '-' if None."""
    if val is None:
        return "-"
    return f"{val:.{decimals}f}"


def _fmt_int(val: Optional[int | float]) -> str:
    if val is None:
        return "-"
    return f"{int(val):,}"


def _fmt_usd(val: Optional[float]) -> str:
    if val is None:
        return "-"
    return f"${val:.4f}"


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    """Build an aligned markdown table."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(cell))

    def _pad_row(cells: list[str]) -> str:
        parts = []
        for i, cell in enumerate(cells):
            w = widths[i] if i < len(widths) else len(cell)
            parts.append(cell.ljust(w))
        return "| " + " | ".join(parts) + " |"

    lines = [
        _pad_row(headers),
        "| " + " | ".join("-" * w for w in widths) + " |",
    ]
    for row in rows:
        lines.append(_pad_row(row))
    return "\n".join(lines)


def _write_csv(path: Path, headers: list[str], rows: list[list[str]]) -> None:
    """Write a CSV file."""
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Table builders
# ---------------------------------------------------------------------------

def _build_run_inventory(runs: list[RunMetrics]) -> tuple[list[str], list[list[str]]]:
    """Table 1: Run Inventory."""
    headers = ["Benchmark", "Config", "Model", "MCP Mode", "Tasks", "Timestamp"]
    rows = []
    for r in runs:
        hc = r.harness_config or {}
        mcp_mode = hc.get("mcp_mode") or r.config_name
        rows.append([
            r.benchmark,
            r.config_name,
            r.model,
            mcp_mode,
            str(r.task_count),
            r.timestamp,
        ])
    return headers, rows


def _build_aggregate_performance(runs: list[RunMetrics]) -> tuple[list[str], list[list[str]]]:
    """Table 2: Aggregate Performance per config across all benchmarks."""
    headers = ["Config", "Mean Reward", "Pass Rate", "Tasks"]

    # Group runs by config_name
    config_runs: dict[str, list[RunMetrics]] = {}
    for r in runs:
        config_runs.setdefault(r.config_name, []).append(r)

    rows = []
    for config in sorted(config_runs):
        all_tasks = []
        for r in config_runs[config]:
            all_tasks.extend(r.tasks)

        rewards = [t.reward for t in all_tasks if t.reward is not None]
        passed = sum(1 for t in all_tasks if t.status == "passed")
        scored = sum(1 for t in all_tasks if t.status in ("passed", "failed"))

        mean_reward = mean(rewards) if rewards else None
        pass_rate = passed / scored if scored > 0 else None

        rows.append([
            config,
            _fmt(mean_reward),
            _fmt(pass_rate),
            str(len(all_tasks)),
        ])
    return headers, rows


def _build_per_benchmark_breakdown(runs: list[RunMetrics]) -> tuple[list[str], list[list[str]]]:
    """Table 3: Mean reward per benchmark x config matrix."""
    benchmarks = sorted({r.benchmark for r in runs})
    configs = sorted({r.config_name for r in runs})

    # Build lookup
    lookup: dict[tuple[str, str], RunMetrics] = {}
    for r in runs:
        lookup[(r.benchmark, r.config_name)] = r

    headers = ["Benchmark"] + configs
    rows = []
    for bench in benchmarks:
        row = [bench]
        for config in configs:
            r = lookup.get((bench, config))
            row.append(_fmt(r.mean_reward) if r else "-")
        rows.append(row)
    return headers, rows


def _build_efficiency(runs: list[RunMetrics]) -> tuple[list[str], list[list[str]]]:
    """Table 4: Efficiency metrics per config x benchmark.

    Primary timing metric is Mean Task Time (agent execution seconds) —
    the time the agent spends solving the task including tool use,
    searching, and coding.  Excludes Docker build and verifier time.
    Wall clock is retained for reference.
    """
    headers = [
        "Benchmark", "Config",
        "Mean Input Tokens", "Mean Output Tokens", "Mean Cache Tokens",
        "Mean Task Time (s)", "Mean Wall Clock (s)", "Mean Cost (USD)",
    ]
    rows = []
    for r in sorted(runs, key=lambda x: (x.benchmark, x.config_name)):
        input_tok = _safe_mean([t.input_tokens for t in r.tasks])
        output_tok = _safe_mean([t.output_tokens for t in r.tasks])
        cache_tok = _safe_mean([
            (t.cache_creation_tokens or 0) + (t.cache_read_tokens or 0)
            for t in r.tasks
            if t.cache_creation_tokens is not None or t.cache_read_tokens is not None
        ])
        rows.append([
            r.benchmark,
            r.config_name,
            _fmt_int(input_tok),
            _fmt_int(output_tok),
            _fmt_int(cache_tok),
            _fmt(r.mean_agent_execution, 1),
            _fmt(r.mean_wall_clock, 1),
            _fmt_usd(_safe_mean([t.cost_usd for t in r.tasks])),
        ])
    return headers, rows


def _build_tool_utilization(runs: list[RunMetrics]) -> tuple[list[str], list[list[str]]]:
    """Table 5: Tool utilization per config x benchmark."""
    headers = [
        "Benchmark", "Config",
        "Mean Total Calls", "Mean MCP Calls", "Mean Local Calls", "Mean MCP Ratio",
    ]
    rows = []
    for r in sorted(runs, key=lambda x: (x.benchmark, x.config_name)):
        rows.append([
            r.benchmark,
            r.config_name,
            _fmt(_safe_mean([t.tool_calls_total for t in r.tasks]), 1),
            _fmt(_safe_mean([t.tool_calls_mcp for t in r.tasks]), 1),
            _fmt(_safe_mean([t.tool_calls_local for t in r.tasks]), 1),
            _fmt(r.mean_mcp_ratio),
        ])
    return headers, rows


def _build_sdlc_phase_breakdown(runs: list[RunMetrics]) -> Optional[tuple[list[str], list[list[str]]]]:
    """Table: Mean reward by SDLC phase x config (requires enriched tasks)."""
    # Check if any tasks have sdlc_phase set
    all_tasks = [t for r in runs for t in r.tasks if t.sdlc_phase]
    if not all_tasks:
        return None

    configs = sorted({r.config_name for r in runs})
    phases = sorted({t.sdlc_phase for t in all_tasks})

    # Build lookup: (phase, config) -> list of rewards
    lookup: dict[tuple[str, str], list[float]] = {}
    for r in runs:
        for t in r.tasks:
            if t.sdlc_phase and t.reward is not None:
                lookup.setdefault((t.sdlc_phase, r.config_name), []).append(t.reward)

    headers = ["SDLC Phase", "Tasks"] + configs
    rows = []
    for phase in phases:
        task_count = sum(1 for t in all_tasks if t.sdlc_phase == phase)
        # Avoid double-counting across configs — count unique task_ids
        unique_ids = {t.task_id for t in all_tasks if t.sdlc_phase == phase}
        row = [phase, str(len(unique_ids))]
        for config in configs:
            rewards = lookup.get((phase, config), [])
            row.append(_fmt(_safe_mean(rewards)) if rewards else "-")
        rows.append(row)
    return headers, rows


def _build_language_breakdown(runs: list[RunMetrics]) -> Optional[tuple[list[str], list[list[str]]]]:
    """Table: Mean reward by language x config (requires enriched tasks)."""
    all_tasks = [t for r in runs for t in r.tasks if t.language]
    if not all_tasks:
        return None

    configs = sorted({r.config_name for r in runs})
    languages = sorted({t.language for t in all_tasks})

    lookup: dict[tuple[str, str], list[float]] = {}
    for r in runs:
        for t in r.tasks:
            if t.language and t.reward is not None:
                lookup.setdefault((t.language, r.config_name), []).append(t.reward)

    headers = ["Language", "Tasks"] + configs
    rows = []
    for lang in languages:
        unique_ids = {t.task_id for t in all_tasks if t.language == lang}
        row = [lang, str(len(unique_ids))]
        for config in configs:
            rewards = lookup.get((lang, config), [])
            row.append(_fmt(_safe_mean(rewards)) if rewards else "-")
        rows.append(row)
    return headers, rows


def _build_mcp_benefit_correlation(runs: list[RunMetrics]) -> Optional[tuple[list[str], list[list[str]]]]:
    """Table: Mean reward by MCP benefit score bucket x config."""
    all_tasks = [t for r in runs for t in r.tasks if t.mcp_benefit_score is not None]
    if not all_tasks:
        return None

    configs = sorted({r.config_name for r in runs})

    # Bucket scores into ranges
    buckets = [
        ("0.0-0.4 (low)", 0.0, 0.4),
        ("0.4-0.6 (medium)", 0.4, 0.6),
        ("0.6-0.8 (high)", 0.6, 0.8),
        ("0.8-1.0 (very high)", 0.8, 1.01),
    ]

    lookup: dict[tuple[str, str], list[float]] = {}
    task_counts: dict[str, set[str]] = {}
    for r in runs:
        for t in r.tasks:
            if t.mcp_benefit_score is None or t.reward is None:
                continue
            for label, lo, hi in buckets:
                if lo <= t.mcp_benefit_score < hi:
                    lookup.setdefault((label, r.config_name), []).append(t.reward)
                    task_counts.setdefault(label, set()).add(t.task_id)
                    break

    headers = ["MCP Benefit Score", "Tasks"] + configs
    rows = []
    for label, lo, hi in buckets:
        unique = task_counts.get(label, set())
        row = [label, str(len(unique))]
        for config in configs:
            rewards = lookup.get((label, config), [])
            row.append(_fmt(_safe_mean(rewards)) if rewards else "-")
        rows.append(row)
    return headers, rows


def _build_search_patterns(runs: list[RunMetrics]) -> Optional[tuple[list[str], list[list[str]]]]:
    """Table: Search pattern metrics per config x benchmark."""
    # Only show if any run has search data
    has_data = any(
        t.search_calls_keyword is not None or t.search_calls_nls is not None
        for r in runs for t in r.tasks
    )
    if not has_data:
        return None

    headers = [
        "Benchmark", "Config",
        "Mean Keyword Searches", "Mean NLS Searches", "Mean Deep Searches",
        "Mean DS/KW Ratio",
    ]
    rows = []
    for r in sorted(runs, key=lambda x: (x.benchmark, x.config_name)):
        rows.append([
            r.benchmark,
            r.config_name,
            _fmt(_safe_mean([t.search_calls_keyword for t in r.tasks]), 1),
            _fmt(_safe_mean([t.search_calls_nls for t in r.tasks]), 1),
            _fmt(_safe_mean([t.search_calls_deepsearch for t in r.tasks]), 1),
            _fmt(r.mean_deepsearch_keyword_ratio),
        ])
    return headers, rows


def _build_code_changes(runs: list[RunMetrics]) -> Optional[tuple[list[str], list[list[str]]]]:
    """Table: Code change metrics per config x benchmark."""
    has_data = any(
        t.files_modified is not None
        for r in runs for t in r.tasks
    )
    if not has_data:
        return None

    headers = [
        "Benchmark", "Config",
        "Mean Files Modified", "Mean Lines Added", "Mean Lines Removed",
    ]
    rows = []
    for r in sorted(runs, key=lambda x: (x.benchmark, x.config_name)):
        rows.append([
            r.benchmark,
            r.config_name,
            _fmt(_safe_mean([t.files_modified for t in r.tasks]), 1),
            _fmt(_safe_mean([t.lines_added for t in r.tasks]), 1),
            _fmt(_safe_mean([t.lines_removed for t in r.tasks]), 1),
        ])
    return headers, rows


def _build_cache_efficiency(runs: list[RunMetrics]) -> Optional[tuple[list[str], list[list[str]]]]:
    """Table: Cache efficiency metrics per config x benchmark."""
    has_data = any(
        t.cache_hit_rate is not None or t.input_output_ratio is not None
        for r in runs for t in r.tasks
    )
    if not has_data:
        return None

    headers = [
        "Benchmark", "Config",
        "Mean Cache Hit Rate", "Mean Input/Output Ratio", "Mean Cost (USD)",
    ]
    rows = []
    for r in sorted(runs, key=lambda x: (x.benchmark, x.config_name)):
        rows.append([
            r.benchmark,
            r.config_name,
            _fmt(r.mean_cache_hit_rate),
            _fmt(r.mean_input_output_ratio, 1),
            _fmt_usd(_safe_mean([t.cost_usd for t in r.tasks])),
        ])
    return headers, rows


def _pearson_r(xs: list[float], ys: list[float]) -> Optional[float]:
    """Pearson correlation coefficient. Returns None if fewer than 2 paired points."""
    n = len(xs)
    if n < 2:
        return None
    # Use statistics.correlation if available (Python 3.10+)
    try:
        from statistics import correlation
        return correlation(xs, ys)
    except (ImportError, AttributeError):
        pass
    # Manual fallback
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = sum((x - mean_x) ** 2 for x in xs) ** 0.5
    den_y = sum((y - mean_y) ** 2 for y in ys) ** 0.5
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


def _build_dual_score_per_task(runs: list[RunMetrics]) -> Optional[tuple[list[str], list[list[str]]]]:
    """Table: Per-task dual scores (verifier reward vs judge score), flagging divergent cases."""
    judged_tasks = [
        (r.benchmark, r.config_name, t)
        for r in runs
        for t in r.tasks
        if t.judge_score is not None
    ]
    if not judged_tasks:
        return None

    headers = [
        "Benchmark", "Config", "Task ID",
        "Verifier Reward", "Judge Score", "Delta", "Oracle Confidence",
    ]
    rows = []
    for bench, config, t in sorted(judged_tasks, key=lambda x: (x[0], x[1], x[2].task_id)):
        verifier = t.reward
        judge = t.judge_score
        delta = None if (verifier is None or judge is None) else judge - verifier
        flag = ""
        if delta is not None and abs(delta) > 0.3:
            flag = " [DIVERGENT]"
        rows.append([
            bench,
            config,
            t.task_id,
            _fmt(verifier),
            _fmt(judge),
            (_fmt(delta) + flag) if delta is not None else "-",
            t.oracle_confidence or "-",
        ])
    return headers, rows


def _build_dual_score_aggregate(runs: list[RunMetrics]) -> Optional[tuple[list[str], list[list[str]]]]:
    """Table: Aggregate dual scores per suite and config with Pearson r correlation."""
    judged_runs = [r for r in runs if any(t.judge_score is not None for t in r.tasks)]
    if not judged_runs:
        return None

    headers = ["Benchmark", "Config", "Tasks (judged)", "Mean Verifier", "Mean Judge", "Delta", "Pearson r"]
    rows = []
    for r in sorted(judged_runs, key=lambda x: (x.benchmark, x.config_name)):
        judged_tasks = [t for t in r.tasks if t.judge_score is not None]
        n = len(judged_tasks)

        # Paired values for both metrics (both non-None)
        paired = [(t.reward, t.judge_score) for t in judged_tasks
                  if t.reward is not None and t.judge_score is not None]
        paired_v = [p[0] for p in paired]
        paired_j = [p[1] for p in paired]

        mean_v = _safe_mean(paired_v) if paired_v else None
        mean_j = _safe_mean(paired_j) if paired_j else None
        delta = (mean_j - mean_v) if (mean_v is not None and mean_j is not None) else None
        r_val = _pearson_r(paired_v, paired_j)

        rows.append([
            r.benchmark,
            r.config_name,
            str(n),
            _fmt(mean_v),
            _fmt(mean_j),
            _fmt(delta) if delta is not None else "-",
            _fmt(r_val) if r_val is not None else "-",
        ])
    return headers, rows


def _build_swebench_partial(runs: list[RunMetrics]) -> Optional[tuple[list[str], list[list[str]]]]:
    """Table 6: SWE-Bench Pro partial scores per config."""
    swe_runs = [r for r in runs if "swebench" in r.benchmark.lower()]
    if not swe_runs:
        return None

    headers = ["Config", "Mean Partial Score", "Tasks"]
    rows = []
    for r in sorted(swe_runs, key=lambda x: x.config_name):
        rows.append([
            r.config_name,
            _fmt(r.mean_partial_score),
            str(r.task_count),
        ])
    return headers, rows


# ---------------------------------------------------------------------------
# MCP Retrieval Performance tables
# ---------------------------------------------------------------------------

# Type alias: (benchmark, config_name, task_id) -> retrieval metrics dict
_RetrievalData = dict[tuple[str, str, str], dict]


def _has_retrieval_data(retrieval_data: _RetrievalData) -> bool:
    return bool(retrieval_data)


def _build_retrieval_per_task(
    runs: list[RunMetrics],
    retrieval_data: _RetrievalData,
) -> Optional[tuple[list[str], list[list[str]]]]:
    """Table: per-task oracle coverage, time-to-first-hit, repos/orgs touched."""
    # Collect rows for any task that has retrieval data
    rows = []
    for r in sorted(runs, key=lambda x: (x.benchmark, x.config_name)):
        for t in sorted(r.tasks, key=lambda x: x.task_id):
            key = (r.benchmark, r.config_name, t.task_id)
            m = retrieval_data.get(key)
            if m is None:
                continue
            ttfh = m.get("time_to_first_oracle_hit_ms")
            rows.append([
                r.benchmark,
                r.config_name,
                t.task_id,
                _fmt(m.get("oracle_coverage")),
                f"{int(ttfh):,}" if ttfh is not None else "-",
                str(m.get("unique_repos_touched", 0)),
                str(m.get("unique_orgs_touched", 0)),
            ])

    if not rows:
        return None

    headers = [
        "Suite", "Config", "Task",
        "Oracle Coverage", "Time-to-First-Hit (ms)",
        "Repos Touched", "Orgs Touched",
    ]
    return headers, rows


def _build_retrieval_per_suite(
    runs: list[RunMetrics],
    retrieval_data: _RetrievalData,
) -> Optional[tuple[list[str], list[list[str]]]]:
    """Table: per-suite aggregate retrieval metrics."""
    # Group by (benchmark, config_name)
    agg: dict[tuple[str, str], list[dict]] = {}
    for r in runs:
        for t in r.tasks:
            key = (r.benchmark, r.config_name, t.task_id)
            m = retrieval_data.get(key)
            if m is None:
                continue
            gkey = (r.benchmark, r.config_name)
            agg.setdefault(gkey, []).append(m)

    if not agg:
        return None

    headers = [
        "Suite", "Config", "Tasks",
        "Mean Coverage", "Mean Repos Touched", "Mean Orgs Touched",
    ]
    rows = []
    for (bench, config) in sorted(agg.keys()):
        items = agg[(bench, config)]
        n = len(items)
        mean_cov = _safe_mean([m.get("oracle_coverage") for m in items])
        mean_repos = _safe_mean([m.get("unique_repos_touched") for m in items])
        mean_orgs = _safe_mean([m.get("unique_orgs_touched") for m in items])
        rows.append([
            bench,
            config,
            str(n),
            _fmt(mean_cov),
            _fmt(mean_repos, 1),
            _fmt(mean_orgs, 1),
        ])
    return headers, rows


def _build_retrieval_comparison(
    runs: list[RunMetrics],
    retrieval_data: _RetrievalData,
) -> Optional[tuple[list[str], list[list[str]]]]:
    """Table: baseline vs MCP-Full oracle coverage comparison per task."""
    # Identify baseline and mcp configs
    configs = sorted({r.config_name for r in runs})
    # Heuristic: baseline has no "mcp" or "sourcegraph" in name; sg_full has "sourcegraph_full"
    baseline_configs = [c for c in configs if "sourcegraph" not in c.lower() and "mcp" not in c.lower()]
    mcp_configs = [c for c in configs if "sourcegraph_full" in c.lower() or "mcp_full" in c.lower()]

    if not baseline_configs or not mcp_configs:
        return None

    # Build (benchmark, task_id) -> {config -> metrics} lookup
    lookup: dict[tuple[str, str], dict[str, dict]] = {}
    for r in runs:
        for t in r.tasks:
            key = (r.benchmark, r.config_name, t.task_id)
            m = retrieval_data.get(key)
            if m is None:
                continue
            task_key = (r.benchmark, t.task_id)
            lookup.setdefault(task_key, {})[r.config_name] = m

    rows = []
    for (bench, task_id) in sorted(lookup.keys()):
        cmap = lookup[(bench, task_id)]
        for bl_config in baseline_configs:
            for mcp_config in mcp_configs:
                bl = cmap.get(bl_config)
                mcp = cmap.get(mcp_config)
                if bl is None and mcp is None:
                    continue
                bl_cov = bl.get("oracle_coverage") if bl else None
                mcp_cov = mcp.get("oracle_coverage") if mcp else None
                delta = (mcp_cov - bl_cov) if (bl_cov is not None and mcp_cov is not None) else None
                bl_orgs = str(bl.get("unique_orgs_touched", 0)) if bl else "-"
                mcp_orgs = str(mcp.get("unique_orgs_touched", 0)) if mcp else "-"
                rows.append([
                    bench,
                    task_id,
                    _fmt(bl_cov),
                    _fmt(mcp_cov),
                    _fmt(delta) if delta is not None else "-",
                    bl_orgs,
                    mcp_orgs,
                ])

    if not rows:
        return None

    headers = [
        "Suite", "Task",
        "Baseline Coverage", "MCP-Full Coverage", "Delta",
        "Baseline Orgs", "MCP Orgs",
    ]
    return headers, rows


def _build_retrieval_tool_breakdown(
    runs: list[RunMetrics],
    retrieval_data: _RetrievalData,
) -> Optional[tuple[list[str], list[list[str]]]]:
    """Table: which MCP tools drive oracle discovery, aggregated per suite."""
    # Aggregate mcp_tool_counts across all tasks with retrieval data
    # Key: (benchmark, config_name, tool_name) -> total_calls
    tool_agg: dict[tuple[str, str, str], int] = {}
    found_any = False

    for r in runs:
        for t in r.tasks:
            key = (r.benchmark, r.config_name, t.task_id)
            m = retrieval_data.get(key)
            if m is None:
                continue
            mcp_counts = m.get("mcp_tool_counts") or {}
            for tool, count in mcp_counts.items():
                found_any = True
                agg_key = (r.benchmark, r.config_name, tool)
                tool_agg[agg_key] = tool_agg.get(agg_key, 0) + count

    if not found_any:
        return None

    # Sort by (benchmark, config, count desc)
    sorted_items = sorted(
        tool_agg.items(),
        key=lambda x: (x[0][0], x[0][1], -x[1]),
    )

    headers = ["Suite", "Config", "MCP Tool", "Total Calls"]
    rows = [
        [bench, config, tool, str(count)]
        for (bench, config, tool), count in sorted_items
    ]
    return headers, rows


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(
    runs_dir: str | Path,
    output_dir: str | Path,
    write_csv_flag: bool = True,
    selected_tasks_path: Optional[str | Path] = None,
) -> None:
    """Generate the full evaluation report.

    Args:
        runs_dir: Path to Harbor runs/official/ directory.
        output_dir: Output directory for report files.
        write_csv_flag: Whether to write CSV files.
        selected_tasks_path: Optional path to selected_benchmark_tasks.json.
            If provided, runs are filtered to only canonical tasks, and
            SDLC phase / MCP benefit metadata is included in the report.
    """
    runs_dir = Path(runs_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Discover runs
    print(f"Discovering runs in: {runs_dir}")
    runs = discover_runs(runs_dir)

    if not runs:
        print("No runs discovered. Check the --runs-dir path.")
        sys.exit(1)

    # Enrich and optionally filter with task selection metadata
    task_index: dict[str, dict] = {}
    if selected_tasks_path:
        sel_path = Path(selected_tasks_path)
        if sel_path.is_file():
            print(f"Loading task selection: {sel_path}")
            selection = load_selected_tasks(sel_path)
            task_index = build_task_index(selection)
            enrich_runs(runs, task_index)
            pre_count = sum(r.task_count for r in runs)
            runs = filter_runs_to_selected(runs, task_index)
            post_count = sum(r.task_count for r in runs)
            print(f"Filtered to selected tasks: {pre_count} -> {post_count}")
        else:
            print(f"WARNING: selected tasks file not found: {sel_path}", file=sys.stderr)

    # Build EvalReport
    report = EvalReport(
        report_id=f"eval_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
        generated_at=datetime.now(timezone.utc).isoformat(),
        runs=runs,
    )

    # Write JSON
    json_path = output_dir / "eval_report.json"
    report.to_json(json_path)
    print(f"Written: {json_path}")

    # Write harness_configs.json
    harness_configs = {}
    for r in runs:
        if r.harness_config:
            harness_configs[r.run_id] = r.harness_config
    if harness_configs:
        hc_path = output_dir / "harness_configs.json"
        hc_path.write_text(json.dumps(harness_configs, indent=2) + "\n")
        print(f"Written: {hc_path}")

    # Collect MCP retrieval data (backwards-compatible: empty dict if no files found)
    print(f"Collecting retrieval metrics from: {runs_dir}")
    retrieval_data = collect_retrieval_data(runs_dir)
    if retrieval_data:
        print(f"Found retrieval_metrics.json for {len(retrieval_data)} task(s).")
    else:
        print("No retrieval_metrics.json found — MCP Retrieval Performance section will be omitted.")

    # Build all tables
    tables: list[tuple[str, str, list[str], list[list[str]]]] = []

    h, r = _build_run_inventory(runs)
    tables.append(("Run Inventory", "run_inventory", h, r))

    h, r = _build_aggregate_performance(runs)
    tables.append(("Aggregate Performance", "aggregate_performance", h, r))

    h, r = _build_per_benchmark_breakdown(runs)
    tables.append(("Per-Benchmark Breakdown (Mean Reward)", "per_benchmark_breakdown", h, r))

    dual_agg = _build_dual_score_aggregate(runs)
    if dual_agg:
        h, r = dual_agg
        tables.append(("Dual-Score Aggregate (Verifier vs Judge)", "dual_score_aggregate", h, r))

    dual_task = _build_dual_score_per_task(runs)
    if dual_task:
        h, r = dual_task
        tables.append(("Dual-Score Per-Task", "dual_score_per_task", h, r))

    h, r = _build_efficiency(runs)
    tables.append(("Efficiency", "efficiency", h, r))

    h, r = _build_tool_utilization(runs)
    tables.append(("Tool Utilization", "tool_utilization", h, r))

    search = _build_search_patterns(runs)
    if search:
        h, r = search
        tables.append(("Search Patterns", "search_patterns", h, r))

    code_chg = _build_code_changes(runs)
    if code_chg:
        h, r = code_chg
        tables.append(("Code Changes", "code_changes", h, r))

    cache_eff = _build_cache_efficiency(runs)
    if cache_eff:
        h, r = cache_eff
        tables.append(("Cache Efficiency", "cache_efficiency", h, r))

    swe = _build_swebench_partial(runs)
    if swe:
        h, r = swe
        tables.append(("SWE-Bench Pro Partial Scores", "swebench_partial_scores", h, r))

    # SDLC and language tables (only if selection metadata was loaded)
    sdlc = _build_sdlc_phase_breakdown(runs)
    if sdlc:
        h, r = sdlc
        tables.append(("Performance by SDLC Phase", "sdlc_phase_breakdown", h, r))

    lang = _build_language_breakdown(runs)
    if lang:
        h, r = lang
        tables.append(("Performance by Language", "language_breakdown", h, r))

    mcp_corr = _build_mcp_benefit_correlation(runs)
    if mcp_corr:
        h, r = mcp_corr
        tables.append(("Performance by MCP Benefit Score", "mcp_benefit_correlation", h, r))

    # MCP Retrieval Performance section (only when retrieval_metrics.json data exists)
    if _has_retrieval_data(retrieval_data):
        ret_per_task = _build_retrieval_per_task(runs, retrieval_data)
        if ret_per_task:
            h, r = ret_per_task
            tables.append(("MCP Retrieval Performance — Per Task", "retrieval_per_task", h, r))

        ret_per_suite = _build_retrieval_per_suite(runs, retrieval_data)
        if ret_per_suite:
            h, r = ret_per_suite
            tables.append(("MCP Retrieval Performance — Per Suite", "retrieval_per_suite", h, r))

        ret_cmp = _build_retrieval_comparison(runs, retrieval_data)
        if ret_cmp:
            h, r = ret_cmp
            tables.append(("MCP Retrieval Performance — Baseline vs MCP-Full", "retrieval_comparison", h, r))

        ret_tools = _build_retrieval_tool_breakdown(runs, retrieval_data)
        if ret_tools:
            h, r = ret_tools
            tables.append(("MCP Retrieval Performance — Tool Discovery Breakdown", "retrieval_tool_breakdown", h, r))

    # Write REPORT.md
    md_lines = [
        "# CodeScaleBench Evaluation Report",
        "",
        f"Generated: {report.generated_at}",
        f"Report ID: {report.report_id}",
        "",
    ]

    for title, slug, headers, rows in tables:
        md_lines.append(f"## {title}")
        md_lines.append("")
        md_lines.append(_md_table(headers, rows))
        md_lines.append("")

    report_md = output_dir / "REPORT.md"
    report_md.write_text("\n".join(md_lines) + "\n")
    print(f"Written: {report_md}")

    # Write CSVs
    if write_csv_flag:
        for title, slug, headers, rows in tables:
            csv_path = output_dir / f"{slug}.csv"
            _write_csv(csv_path, headers, rows)
            print(f"Written: {csv_path}")

    # Print summary to stdout
    benchmarks = report.benchmarks()
    configs = report.configs()
    total_tasks = sum(r.task_count for r in runs)

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Benchmarks found: {len(benchmarks)} ({', '.join(benchmarks)})")
    print(f"Configs found:    {len(configs)} ({', '.join(configs)})")
    print(f"Total tasks:      {total_tasks}")
    print(f"Total runs:       {len(runs)}")
    print()
    print("Pass rates by config:")
    config_runs: dict[str, list[RunMetrics]] = {}
    for r in runs:
        config_runs.setdefault(r.config_name, []).append(r)
    for config in sorted(config_runs):
        all_tasks = []
        for r in config_runs[config]:
            all_tasks.extend(r.tasks)
        passed = sum(1 for t in all_tasks if t.status == "passed")
        scored = sum(1 for t in all_tasks if t.status in ("passed", "failed"))
        rate = f"{passed}/{scored} ({passed/scored:.1%})" if scored > 0 else "no scored tasks"
        print(f"  {config}: {rate}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate evaluation report from Harbor run data.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 scripts/generate_eval_report.py \\\n"
            "      --runs-dir ./runs/official/ \\\n"
            "      --output-dir ./eval_reports/\n"
            "\n"
            "  python3 scripts/generate_eval_report.py --no-csv\n"
        ),
    )
    parser.add_argument(
        "--runs-dir",
        default="./runs/official/",
        help="Path to the Harbor runs/official/ directory "
             "(default: ./runs/official/)",
    )
    parser.add_argument(
        "--output-dir",
        default="./eval_reports/",
        help="Directory for output files (default: ./eval_reports/)",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        default=True,
        dest="csv",
        help="Write CSV files for each table (default: enabled)",
    )
    parser.add_argument(
        "--no-csv",
        action="store_false",
        dest="csv",
        help="Disable CSV output",
    )
    parser.add_argument(
        "--selected-tasks",
        default="./configs/selected_benchmark_tasks.json",
        help="Path to selected_benchmark_tasks.json for filtering and metadata enrichment "
             "(default: ./configs/selected_benchmark_tasks.json). Set to empty string to disable.",
    )

    args = parser.parse_args()
    selected = args.selected_tasks if args.selected_tasks else None
    generate_report(
        runs_dir=args.runs_dir,
        output_dir=args.output_dir,
        write_csv_flag=args.csv,
        selected_tasks_path=selected,
    )


if __name__ == "__main__":
    main()
