#!/usr/bin/env python3
"""Compare benchmark results across agent configurations.

Shows where configs diverge, highlighting tasks where MCP helps or hurts.

Usage:
    # JSON output
    python3 scripts/compare_configs.py --format json

    # Table output
    python3 scripts/compare_configs.py --format table

    # Filter to one suite
    python3 scripts/compare_configs.py --suite ccb_pytorch --format table

    # Show only divergent tasks (some pass, some fail)
    python3 scripts/compare_configs.py --divergent-only --format table
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from aggregate_status import (
    RUNS_DIR, CONFIGS,
    should_skip, detect_suite, _iter_task_dirs, classify_task,
)


def gather_comparison(
    suite_filter: str | None = None,
    timeout_hours: float = 4.0,
) -> dict:
    """Scan all tasks and group results by (suite, task_name) across configs.

    Dedup policy: when multiple runs exist for the same (suite, task, config),
    keep the one with the latest started_at timestamp. Comparisons are always
    latest-to-latest: the most recent baseline run is compared to the most
    recent sourcegraph_full run, independently per task.

    Returns structured comparison data.
    """
    # task_key = (suite, task_name) -> {config: record}
    task_matrix: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)

    if not RUNS_DIR.exists():
        return _build_comparison({}, suite_filter)

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir() or should_skip(run_dir.name):
            continue

        suite = detect_suite(run_dir.name)
        if suite is None:
            continue
        if suite_filter and suite != suite_filter:
            continue

        for config in CONFIGS:
            config_path = run_dir / config
            if not config_path.is_dir():
                continue

            for task_dir in _iter_task_dirs(config_path):
                record = classify_task(task_dir, timeout_hours)
                record["suite"] = suite
                record["config"] = config
                key = (suite, record["task_name"])
                # Latest started_at wins — explicit timestamp comparison so
                # the policy holds even when run dir names don't sort
                # chronologically.
                existing = task_matrix[key].get(config)
                if existing is None or record.get("started_at", "") >= existing.get("started_at", ""):
                    task_matrix[key][config] = record

    return _build_comparison(task_matrix, suite_filter)


def _status_symbol(status: str) -> str:
    return {
        "completed_pass": "PASS",
        "completed_fail": "FAIL",
        "errored": "ERR",
        "timeout": "TOUT",
        "running": "RUN",
    }.get(status, status)


def _build_comparison(task_matrix, suite_filter) -> dict:
    """Build the comparison output structure."""
    tasks = []
    suite_stats = defaultdict(lambda: {c: {"pass": 0, "fail": 0, "error": 0, "total": 0} for c in CONFIGS})

    for (suite, task_name), configs in sorted(task_matrix.items()):
        row = {
            "suite": suite,
            "task_name": task_name,
            "configs": {},
            "divergent": False,
            "all_pass": True,
            "all_fail": True,
            "baseline_only_fail": False,
            "mcp_only_fail": False,
        }

        statuses = set()
        for config in CONFIGS:
            rec = configs.get(config)
            if rec is None:
                row["configs"][config] = {"status": "missing", "reward": None}
                continue

            status = rec["status"]
            reward = rec.get("reward")
            row["configs"][config] = {
                "status": status,
                "reward": reward,
                "wall_clock_seconds": rec.get("wall_clock_seconds"),
                "error_fingerprint": rec.get("error_fingerprint"),
                "timed_out": rec.get("timed_out", False),
            }

            is_pass = status == "completed_pass"
            statuses.add("pass" if is_pass else "nonpass")

            if is_pass:
                row["all_fail"] = False
                suite_stats[suite][config]["pass"] += 1
            else:
                row["all_pass"] = False
                if status == "errored":
                    suite_stats[suite][config]["error"] += 1
                else:
                    suite_stats[suite][config]["fail"] += 1
            suite_stats[suite][config]["total"] += 1

        # Determine divergence patterns
        if "pass" in statuses and "nonpass" in statuses:
            row["divergent"] = True

            # Check if baseline is the only one failing
            bl = row["configs"].get("baseline", {})
            sg_full = row["configs"].get("sourcegraph_full", {})

            bl_pass = bl.get("status") == "completed_pass"
            sgf_pass = sg_full.get("status") == "completed_pass"

            if not bl_pass and sgf_pass:
                row["baseline_only_fail"] = True
            if bl_pass and not sgf_pass:
                row["mcp_only_fail"] = True

        tasks.append(row)

    # Compute overall stats per config
    config_totals = {}
    for config in CONFIGS:
        p = sum(s[config]["pass"] for s in suite_stats.values())
        t = sum(s[config]["total"] for s in suite_stats.values())
        config_totals[config] = {
            "pass": p,
            "total": t,
            "pass_rate": round(p / t, 4) if t > 0 else 0.0,
        }

    divergent_tasks = [t for t in tasks if t["divergent"]]
    baseline_only_fails = [t for t in tasks if t["baseline_only_fail"]]
    mcp_only_fails = [t for t in tasks if t["mcp_only_fail"]]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config_totals": config_totals,
        "suite_stats": {k: dict(v) for k, v in sorted(suite_stats.items())},
        "summary": {
            "total_tasks": len(tasks),
            "divergent_tasks": len(divergent_tasks),
            "all_pass": sum(1 for t in tasks if t["all_pass"]),
            "all_fail": sum(1 for t in tasks if t["all_fail"]),
            "baseline_only_fail": len(baseline_only_fails),
            "mcp_only_fail": len(mcp_only_fails),
        },
        "tasks": tasks,
    }


TIER_LABELS = {
    "baseline": "IDE-native",
    "sourcegraph_full": "Context infra",
}


def _config_label(config: str, use_labels: bool = False) -> str:
    """Return display label for a config slug."""
    if use_labels:
        return TIER_LABELS.get(config, config.replace("sourcegraph_", "SG_"))
    return config.replace("sourcegraph_", "SG_")


def format_comparison_table(data: dict, use_labels: bool = False) -> str:
    """Format comparison as ASCII table."""
    lines = []
    lines.append(f"Config Comparison Report  (generated: {data['generated_at']})")
    lines.append("")

    # Config totals
    lines.append("OVERALL:")
    for config in CONFIGS:
        ct = data["config_totals"].get(config, {})
        p = ct.get("pass", 0)
        t = ct.get("total", 0)
        rate = ct.get("pass_rate", 0)
        label = _config_label(config, use_labels)
        lines.append(f"  {label:18s}  {p:>3d}/{t:<3d}  ({rate:.0%})")
    lines.append("")

    # Summary
    s = data["summary"]
    lines.append(f"DIVERGENCE ANALYSIS ({s['total_tasks']} unique tasks):")
    lines.append(f"  All pass:           {s['all_pass']:>4d}")
    lines.append(f"  All fail:           {s['all_fail']:>4d}")
    lines.append(f"  Divergent:          {s['divergent_tasks']:>4d}")
    bl_label = _config_label("baseline", use_labels)
    sg_label = _config_label("sourcegraph_full", use_labels)
    lines.append(f"  {bl_label} only fail: {s['baseline_only_fail']:>4d}  ({sg_label} helps)")
    lines.append(f"  {sg_label} only fail: {s['mcp_only_fail']:>4d}  ({sg_label} hurts)")
    lines.append("")

    # Per-suite breakdown
    suite_stats = data.get("suite_stats", {})
    if suite_stats:
        header = f"{'Suite':25s}"
        for cfg in CONFIGS:
            label = _config_label(cfg, use_labels)
            header += f" | {label:>12s}"
        lines.append(header)
        lines.append("-" * len(header))

        for suite, cfgs in sorted(suite_stats.items()):
            row = f"{suite:25s}"
            for cfg in CONFIGS:
                s = cfgs.get(cfg, {})
                p = s.get("pass", 0)
                t = s.get("total", 0)
                row += f" | {p:>4d}/{t:<4d}   "
            lines.append(row)
        lines.append("")

    # Divergent tasks detail
    divergent = [t for t in data["tasks"] if t["divergent"]]
    if divergent:
        lines.append(f"DIVERGENT TASKS ({len(divergent)}):")
        header = f"  {'Suite':20s}  {'Task':30s}"
        for cfg in CONFIGS:
            label = _config_label(cfg, use_labels)
            header += f"  {label:>12s}"
        header += "  Signal"
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))

        for t in divergent:
            row = f"  {t['suite']:20s}  {t['task_name']:30s}"
            for cfg in CONFIGS:
                c = t["configs"].get(cfg, {})
                sym = _status_symbol(c.get("status", "missing"))
                row += f"  {sym:>12s}"
            signal = ""
            if t["baseline_only_fail"]:
                signal = f"{sg_label} helps"
            elif t["mcp_only_fail"]:
                signal = f"{sg_label} hurts"
            row += f"  {signal}"
            lines.append(row)
        lines.append("")

    # All-fail tasks (potential adapter bugs)
    all_fail = [t for t in data["tasks"] if t["all_fail"]]
    if all_fail:
        lines.append(f"ALL-FAIL TASKS ({len(all_fail)}) — likely task/adapter issues:")
        for t in all_fail:
            configs_str = "  ".join(
                f"{_config_label(cfg, use_labels)}={_status_symbol(t['configs'].get(cfg, {}).get('status', 'missing'))}"
                for cfg in CONFIGS
            )
            lines.append(f"  {t['suite']:20s}  {t['task_name']:30s}  {configs_str}")

    return "\n".join(lines)


def _compute_statistical_tests(data: dict) -> dict:
    """Run statistical tests on paired baseline vs SG_full rewards.

    Returns dict with welchs_t, cohens_d, mcnemar, bootstrap_ci keys.
    """
    from csb_metrics.statistics import (
        welchs_t_test, cohens_d, mcnemar_test, bootstrap_ci_dict as bootstrap_ci,
    )

    bl_rewards: list[float] = []
    sg_rewards: list[float] = []
    paired_pass: list[tuple[bool, bool]] = []

    for task in data.get("tasks", []):
        bl = task["configs"].get("baseline", {})
        sg = task["configs"].get("sourcegraph_full", {})
        bl_r = bl.get("reward")
        sg_r = sg.get("reward")
        if bl_r is not None and sg_r is not None:
            bl_rewards.append(bl_r)
            sg_rewards.append(sg_r)
            paired_pass.append((bl_r > 0, sg_r > 0))

    if len(bl_rewards) < 2:
        return {"error": f"Too few paired tasks ({len(bl_rewards)}) for statistics"}

    deltas = [sg - bl for bl, sg in zip(bl_rewards, sg_rewards)]

    return {
        "n_paired": len(bl_rewards),
        "welchs_t": welchs_t_test(bl_rewards, sg_rewards),
        "cohens_d": cohens_d(bl_rewards, sg_rewards),
        "mcnemar": mcnemar_test(paired_pass),
        "bootstrap_ci_delta": bootstrap_ci(deltas),
    }


def _format_stats_section(stats: dict) -> str:
    """Format statistical tests as ASCII table section."""
    lines = []
    lines.append("")
    lines.append("STATISTICAL TESTS (baseline vs SG_full):")

    if "error" in stats:
        lines.append(f"  {stats['error']}")
        return "\n".join(lines)

    lines.append(f"  Paired tasks: {stats['n_paired']}")
    lines.append("")

    t = stats.get("welchs_t", {})
    lines.append(f"  Welch's t-test:")
    lines.append(f"    t={t.get('t_stat', 'N/A')}, p={t.get('p_value', 'N/A')}, "
                  f"df={t.get('df', 'N/A')}")
    lines.append(f"    {'*** Significant ***' if t.get('is_significant') else 'Not significant'}")

    d = stats.get("cohens_d", {})
    lines.append(f"  Effect size (Cohen's d):")
    lines.append(f"    d={d.get('d', 'N/A')} ({d.get('magnitude', 'N/A')})")
    lines.append(f"    95% CI: [{d.get('ci_lower', 'N/A')}, {d.get('ci_upper', 'N/A')}]")

    m = stats.get("mcnemar", {})
    lines.append(f"  McNemar's test (pass/fail):")
    lines.append(f"    chi2={m.get('chi2', 'N/A')}, p={m.get('p_value', 'N/A')}")
    lines.append(f"    BL-fail→SG-pass: {m.get('b', 0)}, BL-pass→SG-fail: {m.get('c', 0)}")
    lines.append(f"    {'*** Significant ***' if m.get('is_significant') else 'Not significant'}")

    bci = stats.get("bootstrap_ci_delta", {})
    lines.append(f"  Bootstrap CI (reward delta):")
    lines.append(f"    estimate={bci.get('estimate', 'N/A')}")
    lines.append(f"    95% CI: [{bci.get('ci_lower', 'N/A')}, {bci.get('ci_upper', 'N/A')}]")

    return "\n".join(lines)


def gather_paired_analysis(suite_filter: str | None = None) -> dict:
    """Build a paired analysis using all valid runs, clipped to min(N_bl, N_sg) per task.

    Loads run_history from MANIFEST and selects the optimal set of paired
    runs for comparative analysis. Prefers paired_rerun batches when available.

    Returns structured analysis with per-task variance and paired comparisons.
    """
    manifest_path = RUNS_DIR / "MANIFEST.json"
    if not manifest_path.is_file():
        return {"error": "MANIFEST.json not found. Run generate_manifest.py first."}

    manifest = json.loads(manifest_path.read_text())
    run_history = manifest.get("run_history", {})

    if not run_history:
        return {"error": "No run_history in MANIFEST. Regenerate with latest generate_manifest.py."}

    # Collect paired data per (suite, task)
    paired_tasks = []
    total_pairs = 0

    # Group run_history by suite
    suite_configs: dict[str, dict[str, dict]] = defaultdict(dict)
    for key, tasks in run_history.items():
        suite, config = key.split("/", 1)
        suite_configs[suite][config] = tasks

    for suite, configs in sorted(suite_configs.items()):
        if suite_filter and suite != suite_filter:
            continue

        bl_tasks = configs.get("baseline", {})
        sg_tasks = configs.get("sourcegraph_full", {})

        # Find tasks present in both configs
        common_tasks = set(bl_tasks.keys()) & set(sg_tasks.keys())

        for task_name in sorted(common_tasks):
            bl_runs = bl_tasks[task_name]["runs"]
            sg_runs = sg_tasks[task_name]["runs"]

            # Select paired runs: min(N_bl, N_sg), preferring paired batches
            n_pairs = min(len(bl_runs), len(sg_runs))
            if n_pairs == 0:
                continue

            # Sort: paired batches first, then by started_at (latest first)
            def _sort_key(r):
                return (-int(r.get("is_paired", False)), r.get("started_at", ""))

            bl_sorted = sorted(bl_runs, key=_sort_key, reverse=True)[:n_pairs]
            sg_sorted = sorted(sg_runs, key=_sort_key, reverse=True)[:n_pairs]

            bl_rewards = [r["reward"] for r in bl_sorted]
            sg_rewards = [r["reward"] for r in sg_sorted]

            import statistics
            bl_mean = round(statistics.mean(bl_rewards), 4)
            sg_mean = round(statistics.mean(sg_rewards), 4)
            delta = round(sg_mean - bl_mean, 4)

            entry = {
                "suite": suite,
                "task_name": task_name,
                "n_pairs": n_pairs,
                "n_baseline_total": len(bl_runs),
                "n_sg_full_total": len(sg_runs),
                "baseline_mean_reward": bl_mean,
                "sg_full_mean_reward": sg_mean,
                "delta": delta,
                "baseline_rewards": bl_rewards,
                "sg_full_rewards": sg_rewards,
            }

            if n_pairs > 1:
                entry["baseline_std"] = round(statistics.stdev(bl_rewards), 4)
                entry["sg_full_std"] = round(statistics.stdev(sg_rewards), 4)

            # Flag flaky tasks (variance > 0 in either config)
            entry["flaky"] = len(set(bl_rewards)) > 1 or len(set(sg_rewards)) > 1

            paired_tasks.append(entry)
            total_pairs += n_pairs

    # Aggregate stats
    all_bl = [t["baseline_mean_reward"] for t in paired_tasks]
    all_sg = [t["sg_full_mean_reward"] for t in paired_tasks]
    all_deltas = [t["delta"] for t in paired_tasks]

    import statistics
    summary = {
        "total_tasks": len(paired_tasks),
        "total_pairs_used": total_pairs,
        "flaky_tasks": sum(1 for t in paired_tasks if t["flaky"]),
        "tasks_with_multiple_runs": sum(1 for t in paired_tasks if t["n_pairs"] > 1),
    }
    if all_bl:
        summary["baseline_mean"] = round(statistics.mean(all_bl), 4)
        summary["sg_full_mean"] = round(statistics.mean(all_sg), 4)
        summary["mean_delta"] = round(statistics.mean(all_deltas), 4)
        if len(all_deltas) > 1:
            summary["std_delta"] = round(statistics.stdev(all_deltas), 4)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analysis_type": "paired_min_runs",
        "description": "Comparative analysis using min(N_baseline, N_sg_full) valid runs per task, preferring paired batches",
        "summary": summary,
        "tasks": paired_tasks,
    }


def format_paired_analysis_table(data: dict) -> str:
    """Format paired analysis as ASCII table."""
    lines = []
    lines.append(f"Paired Analysis Report  (generated: {data['generated_at']})")
    lines.append(f"Method: {data['description']}")
    lines.append("")

    s = data["summary"]
    lines.append(f"  Tasks compared:       {s['total_tasks']}")
    lines.append(f"  Total run pairs used: {s['total_pairs_used']}")
    lines.append(f"  Tasks w/ multi-runs:  {s['tasks_with_multiple_runs']}")
    lines.append(f"  Flaky tasks:          {s['flaky_tasks']}")
    if "baseline_mean" in s:
        lines.append(f"  Baseline mean reward: {s['baseline_mean']:.4f}")
        lines.append(f"  SG_full mean reward:  {s['sg_full_mean']:.4f}")
        lines.append(f"  Mean delta:           {s['mean_delta']:+.4f}")
        if "std_delta" in s:
            lines.append(f"  Std delta:            {s['std_delta']:.4f}")
    lines.append("")

    # Per-task detail
    header = f"  {'Suite':20s}  {'Task':35s}  {'N':>3s}  {'BL':>6s}  {'SG':>6s}  {'Delta':>7s}  {'Flaky':>5s}"
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))

    for t in data["tasks"]:
        flaky_mark = "  *" if t["flaky"] else ""
        row = (
            f"  {t['suite']:20s}  {t['task_name'][:35]:35s}  "
            f"{t['n_pairs']:>3d}  {t['baseline_mean_reward']:>6.3f}  "
            f"{t['sg_full_mean_reward']:>6.3f}  {t['delta']:>+7.3f}{flaky_mark}"
        )
        lines.append(row)

    return "\n".join(lines)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Compare benchmark results across agent configurations."
    )
    parser.add_argument(
        "--format", choices=["json", "table"], default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--suite", default=None,
        help="Filter to one benchmark suite",
    )
    parser.add_argument(
        "--divergent-only", action="store_true",
        help="Only show tasks where configs diverge",
    )
    parser.add_argument(
        "--timeout-hours", type=float, default=4.0,
        help="Hours before marking as timeout (default: 4)",
    )
    parser.add_argument(
        "--with-stats", action="store_true",
        help="Add statistical significance tests (Welch's t, Cohen's d, McNemar, bootstrap CI)",
    )
    parser.add_argument(
        "--baseline-labels", action="store_true",
        help="Use enterprise-friendly tier labels in table output (baseline -> 'IDE-native', SG_full -> 'Context infra')",
    )
    parser.add_argument(
        "--paired-analysis", action="store_true",
        help="Use paired analysis: min(N_baseline, N_sg_full) runs per task, preferring paired batches. "
             "Reads run_history from MANIFEST.json.",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.paired_analysis:
        data = gather_paired_analysis(suite_filter=args.suite)
        if "error" in data:
            print(f"ERROR: {data['error']}", file=sys.stderr)
            sys.exit(1)
        if args.format == "table":
            print(format_paired_analysis_table(data))
        else:
            print(json.dumps(data, indent=2))
        return

    data = gather_comparison(
        suite_filter=args.suite,
        timeout_hours=args.timeout_hours,
    )

    if args.divergent_only:
        data["tasks"] = [t for t in data["tasks"] if t["divergent"]]

    if args.with_stats:
        data["statistical_tests"] = _compute_statistical_tests(data)

    if args.format == "table":
        output = format_comparison_table(data, use_labels=args.baseline_labels)
        if args.with_stats:
            output += _format_stats_section(data["statistical_tests"])
        print(output)
    else:
        print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
