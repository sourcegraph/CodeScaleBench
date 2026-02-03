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
        --runs-dir ~/evals/custom_agents/agents/claudecode/runs/official/ \
        --output-dir ./eval_reports/
"""

from __future__ import annotations

import argparse
import csv
import io
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

from ccb_metrics import discover_runs, EvalReport, RunMetrics
from ccb_metrics.task_selection import (
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
    """Table 4: Efficiency metrics per config x benchmark."""
    headers = [
        "Benchmark", "Config",
        "Mean Input Tokens", "Mean Output Tokens", "Mean Cache Tokens",
        "Mean Wall Clock (s)", "Mean Cost (USD)",
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

    # Build all tables
    tables: list[tuple[str, str, list[str], list[list[str]]]] = []

    h, r = _build_run_inventory(runs)
    tables.append(("Run Inventory", "run_inventory", h, r))

    h, r = _build_aggregate_performance(runs)
    tables.append(("Aggregate Performance", "aggregate_performance", h, r))

    h, r = _build_per_benchmark_breakdown(runs)
    tables.append(("Per-Benchmark Breakdown (Mean Reward)", "per_benchmark_breakdown", h, r))

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

    # Write REPORT.md
    md_lines = [
        "# CodeContextBench Evaluation Report",
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
            "      --runs-dir ~/evals/custom_agents/agents/claudecode/runs/official/ \\\n"
            "      --output-dir ./eval_reports/\n"
            "\n"
            "  python3 scripts/generate_eval_report.py --no-csv\n"
        ),
    )
    parser.add_argument(
        "--runs-dir",
        default=str(Path.home() / "evals/custom_agents/agents/claudecode/runs/official"),
        help="Path to the Harbor runs/official/ directory "
             "(default: ~/evals/custom_agents/agents/claudecode/runs/official/)",
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
