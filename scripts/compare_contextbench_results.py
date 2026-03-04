#!/usr/bin/env python3
"""Compare baseline vs MCP ContextBench evaluation results.

Reads ContextBench evaluation output (JSONL) for baseline and MCP configs and
produces a side-by-side comparison report with statistical tests.

Usage:
    python3 scripts/compare_contextbench_results.py \\
        --baseline results/contextbench_pilot/baseline_eval.jsonl \\
        --mcp results/contextbench_pilot/mcp_eval.jsonl \\
        --output eval_reports/contextbench_crossval_report.json

    # With gold data for slicing
    python3 scripts/compare_contextbench_results.py \\
        --baseline results/contextbench_pilot/baseline_eval.jsonl \\
        --mcp results/contextbench_pilot/mcp_eval.jsonl \\
        --selection configs/contextbench_pilot_50.json \\
        --output eval_reports/contextbench_crossval_report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent

log = logging.getLogger(__name__)


def _load_eval_results(path: Path) -> dict[str, dict]:
    """Load ContextBench evaluation JSONL into {instance_id: metrics} dict."""
    results = {}
    if not path.exists():
        log.error("Evaluation file not found: %s", path)
        return results

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            iid = entry.get("instance_id", entry.get("inst_id", ""))
            if iid:
                results[iid] = entry

    return results


def _safe_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _safe_median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 0:
        return (s[n // 2 - 1] + s[n // 2]) / 2
    return s[n // 2]


def _extract_metric(entry: dict, metric_path: str, default: float = 0.0) -> float:
    """Extract a metric value from a ContextBench eval result entry.

    Handles nested paths like 'file.coverage' or 'symbol.f1'.
    """
    parts = metric_path.split(".")
    val = entry
    for part in parts:
        if isinstance(val, dict):
            val = val.get(part, default)
        else:
            return default
    try:
        return float(val) if val is not None else default
    except (TypeError, ValueError):
        return default


def _wilcoxon_signed_rank(x: list[float], y: list[float]) -> float:
    """Simple Wilcoxon signed-rank test p-value (two-sided).

    Returns approximate p-value using normal approximation.
    Falls back to 1.0 if scipy unavailable.
    """
    try:
        from scipy.stats import wilcoxon
        if len(x) < 6:
            return 1.0
        stat, p = wilcoxon(x, y, alternative="two-sided")
        return p
    except (ImportError, ValueError):
        return 1.0


def _bootstrap_ci(
    x: list[float], y: list[float], n_boot: int = 10000, ci: float = 0.95
) -> tuple[float, float]:
    """Bootstrap confidence interval for mean(x - y)."""
    if not x or not y or len(x) != len(y):
        return (0.0, 0.0)

    diffs = [a - b for a, b in zip(x, y)]
    rng = random.Random(42)
    boot_means = []
    for _ in range(n_boot):
        sample = [rng.choice(diffs) for _ in range(len(diffs))]
        boot_means.append(sum(sample) / len(sample))

    boot_means.sort()
    alpha = (1 - ci) / 2
    lo = boot_means[int(alpha * n_boot)]
    hi = boot_means[int((1 - alpha) * n_boot)]
    return (round(lo, 4), round(hi, 4))


# ContextBench metric paths to extract
# These may vary based on ContextBench version; we try common paths
METRIC_NAMES = {
    "file_coverage": ["file_coverage", "file.coverage", "coverage_file"],
    "file_precision": ["file_precision", "file.precision", "precision_file"],
    "file_f1": ["file_f1", "file.f1", "f1_file"],
    "span_coverage": ["span_coverage", "span.coverage", "coverage_span"],
    "symbol_coverage": ["symbol_coverage", "symbol.coverage", "coverage_symbol"],
    "editloc_recall": ["editloc_recall", "editloc.recall", "edit_loc_recall"],
    "auc_coverage": ["auc_coverage", "auc.coverage"],
    "redundancy": ["redundancy"],
}


def _get_metric(entry: dict, metric_key: str) -> float | None:
    """Try multiple paths to extract a metric."""
    for path in METRIC_NAMES.get(metric_key, [metric_key]):
        val = _extract_metric(entry, path, default=None)
        if val is not None:
            return val
    return None


def compare(
    baseline_path: Path,
    mcp_path: Path,
    selection_path: Path | None = None,
    output_path: Path | None = None,
) -> dict:
    """Run comparison and return report dict."""

    baseline_results = _load_eval_results(baseline_path)
    mcp_results = _load_eval_results(mcp_path)

    log.info("Loaded %d baseline, %d MCP results", len(baseline_results), len(mcp_results))

    # Load selection for metadata (language, complexity)
    selection_meta = {}
    if selection_path and selection_path.exists():
        sel = json.loads(selection_path.read_text())
        for task in sel.get("tasks", []):
            iid = task.get("instance_id", "")
            if iid:
                selection_meta[iid] = {
                    "language": task.get("language", "unknown"),
                    "complexity": task.get("complexity", "unknown"),
                    "repo": task.get("repo", ""),
                }

    # Find paired instances (present in both baseline and MCP)
    paired_ids = sorted(set(baseline_results.keys()) & set(mcp_results.keys()))
    log.info("Paired instances: %d", len(paired_ids))

    if not paired_ids:
        log.error("No paired instances found. Check instance_id mapping.")
        return {"error": "no_paired_instances"}

    # Compute per-metric paired comparisons
    metrics_to_compare = [
        "file_coverage", "file_precision", "file_f1",
        "span_coverage", "symbol_coverage",
        "editloc_recall", "auc_coverage", "redundancy",
    ]

    paired_data: dict[str, dict[str, list[float]]] = {
        m: {"baseline": [], "mcp": []} for m in metrics_to_compare
    }
    per_task_results = []

    for iid in paired_ids:
        bl = baseline_results[iid]
        mc = mcp_results[iid]
        meta = selection_meta.get(iid, {})

        task_entry = {
            "instance_id": iid,
            "language": meta.get("language", "unknown"),
            "complexity": meta.get("complexity", "unknown"),
            "repo": meta.get("repo", ""),
        }

        for metric in metrics_to_compare:
            bl_val = _get_metric(bl, metric)
            mc_val = _get_metric(mc, metric)
            if bl_val is not None and mc_val is not None:
                paired_data[metric]["baseline"].append(bl_val)
                paired_data[metric]["mcp"].append(mc_val)
                task_entry[f"bl_{metric}"] = round(bl_val, 4)
                task_entry[f"mcp_{metric}"] = round(mc_val, 4)
                task_entry[f"delta_{metric}"] = round(mc_val - bl_val, 4)

        per_task_results.append(task_entry)

    # Aggregate metrics
    aggregate = {}
    for metric in metrics_to_compare:
        bl_vals = paired_data[metric]["baseline"]
        mc_vals = paired_data[metric]["mcp"]
        if not bl_vals:
            continue

        bl_mean = _safe_mean(bl_vals)
        mc_mean = _safe_mean(mc_vals)
        delta = mc_mean - bl_mean
        pct = (delta / bl_mean * 100) if bl_mean > 0 else 0

        p_value = _wilcoxon_signed_rank(mc_vals, bl_vals)
        ci_lo, ci_hi = _bootstrap_ci(mc_vals, bl_vals)

        # Win/loss/tie
        wins = sum(1 for m, b in zip(mc_vals, bl_vals) if m > b + 0.001)
        losses = sum(1 for m, b in zip(mc_vals, bl_vals) if b > m + 0.001)
        ties = len(bl_vals) - wins - losses

        aggregate[metric] = {
            "n": len(bl_vals),
            "baseline_mean": round(bl_mean, 4),
            "mcp_mean": round(mc_mean, 4),
            "delta": round(delta, 4),
            "delta_pct": round(pct, 1),
            "p_value": round(p_value, 4),
            "ci_95": [ci_lo, ci_hi],
            "mcp_wins": wins,
            "bl_wins": losses,
            "ties": ties,
        }

    # Slice by language
    by_language: dict[str, dict] = defaultdict(lambda: {"baseline": [], "mcp": [], "n": 0})
    for task in per_task_results:
        lang = task.get("language", "unknown")
        bl_f1 = task.get("bl_file_f1")
        mc_f1 = task.get("mcp_file_f1")
        if bl_f1 is not None and mc_f1 is not None:
            by_language[lang]["baseline"].append(bl_f1)
            by_language[lang]["mcp"].append(mc_f1)
            by_language[lang]["n"] += 1

    language_summary = {}
    for lang, data in sorted(by_language.items()):
        language_summary[lang] = {
            "n": data["n"],
            "bl_file_f1": round(_safe_mean(data["baseline"]), 4),
            "mcp_file_f1": round(_safe_mean(data["mcp"]), 4),
            "delta": round(_safe_mean(data["mcp"]) - _safe_mean(data["baseline"]), 4),
        }

    # Slice by complexity
    by_complexity: dict[str, dict] = defaultdict(lambda: {"baseline": [], "mcp": [], "n": 0})
    for task in per_task_results:
        complexity = task.get("complexity", "unknown")
        bl_f1 = task.get("bl_file_f1")
        mc_f1 = task.get("mcp_file_f1")
        if bl_f1 is not None and mc_f1 is not None:
            by_complexity[complexity]["baseline"].append(bl_f1)
            by_complexity[complexity]["mcp"].append(mc_f1)
            by_complexity[complexity]["n"] += 1

    complexity_summary = {}
    for comp, data in sorted(by_complexity.items()):
        complexity_summary[comp] = {
            "n": data["n"],
            "bl_file_f1": round(_safe_mean(data["baseline"]), 4),
            "mcp_file_f1": round(_safe_mean(data["mcp"]), 4),
            "delta": round(_safe_mean(data["mcp"]) - _safe_mean(data["baseline"]), 4),
        }

    report = {
        "metadata": {
            "total_baseline": len(baseline_results),
            "total_mcp": len(mcp_results),
            "paired": len(paired_ids),
            "baseline_file": str(baseline_path),
            "mcp_file": str(mcp_path),
        },
        "aggregate": aggregate,
        "by_language": language_summary,
        "by_complexity": complexity_summary,
        "per_task": per_task_results,
    }

    # Print terminal summary
    print("\n" + "=" * 72)
    print("ContextBench Cross-Validation Report")
    print("=" * 72)
    print(f"Paired tasks: {len(paired_ids)}")
    print()

    header = f"{'Metric':<25} {'Baseline':>10} {'MCP':>10} {'Delta':>10} {'p-value':>10}"
    print(header)
    print("-" * len(header))
    for metric, data in aggregate.items():
        print(
            f"{metric:<25} {data['baseline_mean']:>10.4f} "
            f"{data['mcp_mean']:>10.4f} {data['delta']:>+10.4f} "
            f"{data['p_value']:>10.4f}"
        )

    if language_summary:
        print(f"\nBy Language (file F1):")
        for lang, data in language_summary.items():
            print(
                f"  {lang:<15} ({data['n']:>2} tasks): "
                f"BL={data['bl_file_f1']:.3f}  MCP={data['mcp_file_f1']:.3f}  "
                f"Delta={data['delta']:+.3f}"
            )

    if complexity_summary:
        print(f"\nBy Complexity (file F1):")
        for comp, data in complexity_summary.items():
            print(
                f"  {comp:<15} ({data['n']:>2} tasks): "
                f"BL={data['bl_file_f1']:.3f}  MCP={data['mcp_file_f1']:.3f}  "
                f"Delta={data['delta']:+.3f}"
            )

    # Win/loss summary for file_f1
    f1_data = aggregate.get("file_f1", {})
    if f1_data:
        print(f"\nFile F1 Win/Loss:")
        print(
            f"  MCP wins: {f1_data.get('mcp_wins', 0)}  "
            f"BL wins: {f1_data.get('bl_wins', 0)}  "
            f"Ties: {f1_data.get('ties', 0)}"
        )
        ci = f1_data.get("ci_95", [0, 0])
        print(f"  Bootstrap 95% CI for delta: [{ci[0]:+.4f}, {ci[1]:+.4f}]")

    print("=" * 72)

    # Write output
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2) + "\n")
        log.info("Wrote report: %s", output_path)

    return report


def main():
    parser = argparse.ArgumentParser(
        description="Compare baseline vs MCP ContextBench results"
    )
    parser.add_argument("--baseline", type=Path, required=True, help="Baseline eval JSONL")
    parser.add_argument("--mcp", type=Path, required=True, help="MCP eval JSONL")
    parser.add_argument("--selection", type=Path, default=None, help="Pilot selection JSON")
    parser.add_argument("--output", type=Path, default=None, help="Output report path")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    compare(args.baseline, args.mcp, args.selection, args.output)


if __name__ == "__main__":
    main()
