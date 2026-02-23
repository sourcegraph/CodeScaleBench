#!/usr/bin/env python3
"""Compute file-level retrieval metrics from normalized retrieval events.

Reads ``*.retrieval_events.json`` files produced by
``normalize_retrieval_events.py`` and computes standard IR metrics:
precision@K, recall@K, F1@K, MRR, nDCG@K, MAP, file-level recall,
and context efficiency.

Emits task-level and run-level aggregates in machine-readable JSON.

Usage:
    python3 scripts/compute_retrieval_metrics.py --run-dir runs/staging/fix_haiku_20260223
    python3 scripts/compute_retrieval_metrics.py --run-dir runs/staging --all
    python3 scripts/compute_retrieval_metrics.py --events-dir runs/staging/fix_haiku_20260223/retrieval_events
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Repository root
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from ccb_metrics.ir_metrics import (
    precision_at_k,
    recall_at_k,
    f1_at_k,
    mrr,
    ndcg_at_k,
    mean_average_precision,
    file_level_recall,
    context_efficiency,
    _normalize,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_K_VALUES = [1, 3, 5, 10]


# ---------------------------------------------------------------------------
# Metric computation from normalized events
# ---------------------------------------------------------------------------

def compute_task_metrics(doc: dict, k_values: list[int] | None = None) -> dict | None:
    """Compute IR metrics for a single task from its normalized events doc.

    Returns None if no ground truth or no events (non-computable).
    """
    if k_values is None:
        k_values = DEFAULT_K_VALUES

    coverage = doc.get("coverage", {})
    gt = doc.get("ground_truth", {})
    gt_files = gt.get("files", [])
    events = doc.get("events", [])

    has_gt = coverage.get("has_ground_truth", False)
    if not has_gt or not gt_files:
        return None

    # Build ordered retrieved file list (first-seen, unique)
    retrieved: list[str] = []
    seen: set[str] = set()
    for evt in events:
        for tf in evt.get("target_files", []):
            norm = _normalize(tf)
            if norm and norm not in seen:
                seen.add(norm)
                retrieved.append(norm)

    relevant = {_normalize(f) for f in gt_files}

    # Zero-retrieval: metrics are 0 except recall denominator is handled
    prec = {}
    rec = {}
    f1 = {}
    ndcg = {}
    for k in k_values:
        prec[k] = round(precision_at_k(retrieved, relevant, k), 4)
        rec[k] = round(recall_at_k(retrieved, relevant, k), 4)
        f1[k] = round(f1_at_k(retrieved, relevant, k), 4)
        ndcg[k] = round(ndcg_at_k(retrieved, relevant, k), 4)

    mrr_val = round(mrr(retrieved, relevant), 4)
    map_val = round(mean_average_precision(retrieved, relevant), 4)
    file_rec = round(file_level_recall(retrieved, relevant), 4)
    ctx_eff = round(context_efficiency(retrieved, relevant), 4)

    # Overlap
    norm_retrieved = {_normalize(f) for f in retrieved}
    overlap = relevant & norm_retrieved

    # Time-to-context from events
    summary = doc.get("summary", {})
    first_gt_step = summary.get("first_ground_truth_hit_step")

    # Find elapsed time at first GT hit
    ttfr_seconds: float | None = None
    ttfr_tokens: int | None = None
    if first_gt_step is not None:
        for evt in events:
            if evt["step_index"] == first_gt_step:
                ttfr_seconds = evt.get("elapsed_seconds")
                ttfr_tokens = evt.get("cumulative_tokens")
                break

    provenance = doc.get("provenance", {})

    return {
        "task_name": provenance.get("task_name", "unknown"),
        "config_name": provenance.get("config_name", "unknown"),
        "benchmark": provenance.get("benchmark", "unknown"),
        "precision": prec,
        "recall": rec,
        "f1": f1,
        "mrr": mrr_val,
        "ndcg": ndcg,
        "map_score": map_val,
        "file_recall": file_rec,
        "context_efficiency": ctx_eff,
        "n_retrieved": len(retrieved),
        "n_ground_truth": len(relevant),
        "n_overlap": len(overlap),
        "first_gt_hit_step": first_gt_step,
        "ttfr_seconds": ttfr_seconds,
        "ttfr_tokens": ttfr_tokens,
        "trace_source": coverage.get("trace_source"),
        "ground_truth_confidence": coverage.get("ground_truth_confidence"),
    }


def aggregate_metrics(task_metrics: list[dict]) -> dict:
    """Compute run-level aggregate statistics over task metrics."""
    if not task_metrics:
        return {"n_tasks": 0}

    # Collect scalar metrics
    scalars = {
        "mrr": [m["mrr"] for m in task_metrics],
        "map_score": [m["map_score"] for m in task_metrics],
        "file_recall": [m["file_recall"] for m in task_metrics],
        "context_efficiency": [m["context_efficiency"] for m in task_metrics],
    }

    # @K metrics
    k_values = set()
    for m in task_metrics:
        k_values.update(m["precision"].keys())
    k_values = sorted(k_values, key=lambda x: int(x) if isinstance(x, (int, str)) else x)

    for k in k_values:
        k_int = int(k)
        scalars[f"precision@{k_int}"] = [m["precision"].get(k, m["precision"].get(k_int, 0.0)) for m in task_metrics]
        scalars[f"recall@{k_int}"] = [m["recall"].get(k, m["recall"].get(k_int, 0.0)) for m in task_metrics]
        scalars[f"f1@{k_int}"] = [m["f1"].get(k, m["f1"].get(k_int, 0.0)) for m in task_metrics]
        scalars[f"ndcg@{k_int}"] = [m["ndcg"].get(k, m["ndcg"].get(k_int, 0.0)) for m in task_metrics]

    result: dict = {}
    for name, values in scalars.items():
        result[name] = {
            "mean": round(statistics.mean(values), 4),
            "std": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
            "median": round(statistics.median(values), 4),
            "n": len(values),
        }

    # Time-to-context
    ttfr_vals = [m["ttfr_seconds"] for m in task_metrics if m.get("ttfr_seconds") is not None]
    if ttfr_vals:
        result["ttfr_seconds"] = {
            "mean": round(statistics.mean(ttfr_vals), 1),
            "std": round(statistics.stdev(ttfr_vals), 1) if len(ttfr_vals) > 1 else 0.0,
            "median": round(statistics.median(ttfr_vals), 1),
            "n": len(ttfr_vals),
        }

    result["_totals"] = {
        "n_tasks": len(task_metrics),
        "mean_retrieved": round(statistics.mean([m["n_retrieved"] for m in task_metrics]), 1),
        "mean_ground_truth": round(statistics.mean([m["n_ground_truth"] for m in task_metrics]), 1),
        "mean_overlap": round(statistics.mean([m["n_overlap"] for m in task_metrics]), 1),
    }

    return result


# ---------------------------------------------------------------------------
# Event file discovery
# ---------------------------------------------------------------------------

def discover_event_files(path: Path) -> list[Path]:
    """Find all .retrieval_events.json files under a directory."""
    return sorted(path.rglob("*.retrieval_events.json"))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute file-level retrieval metrics from normalized events.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Metrics computed:\n"
            "  precision@K, recall@K, F1@K (K=1,3,5,10)\n"
            "  MRR, nDCG@K, MAP\n"
            "  file-level recall, context efficiency\n"
            "\n"
            "Zero-retrieval tasks: all metrics are 0 (except recall@K with\n"
            "empty ground truth returns 1.0 by convention).\n"
            "\n"
            "Zero-ground-truth tasks: skipped (non-computable), reported\n"
            "in the summary.\n"
        ),
    )
    parser.add_argument(
        "--run-dir", type=Path, default=None,
        help="Run directory containing retrieval_events/ subdirectory.",
    )
    parser.add_argument(
        "--events-dir", type=Path, default=None,
        help="Direct path to a retrieval_events/ directory.",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Walk all runs under --run-dir.",
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=None,
        help="Write JSON output to this file (default: stdout).",
    )
    parser.add_argument(
        "--by-suite", action="store_true",
        help="Also aggregate by benchmark suite.",
    )
    parser.add_argument(
        "--by-config", action="store_true",
        help="Also aggregate by config.",
    )
    args = parser.parse_args()

    if not args.run_dir and not args.events_dir:
        parser.error("Provide --run-dir or --events-dir")

    # Discover event files
    event_files: list[Path] = []
    if args.events_dir:
        event_files = discover_event_files(args.events_dir)
    elif args.all:
        # Walk all retrieval_events dirs under run-dir
        for rd in sorted(args.run_dir.iterdir()):
            if rd.is_dir():
                evdir = rd / "retrieval_events"
                if evdir.is_dir():
                    event_files.extend(discover_event_files(evdir))
        # Also check direct retrieval_events in run-dir
        direct = args.run_dir / "retrieval_events"
        if direct.is_dir():
            event_files.extend(discover_event_files(direct))
    else:
        evdir = args.run_dir / "retrieval_events"
        if evdir.is_dir():
            event_files = discover_event_files(evdir)

    if not event_files:
        print("No retrieval event files found. Run normalize_retrieval_events.py first.", file=sys.stderr)
        sys.exit(0)

    # Load and compute
    task_metrics: list[dict] = []
    skipped_no_gt = 0
    skipped_parse_error = 0

    for ef in event_files:
        try:
            doc = json.loads(ef.read_text())
        except (json.JSONDecodeError, OSError):
            skipped_parse_error += 1
            continue

        tm = compute_task_metrics(doc)
        if tm is None:
            skipped_no_gt += 1
            continue
        task_metrics.append(tm)

    # Aggregates
    overall = aggregate_metrics(task_metrics)

    # By-suite aggregates
    by_suite: dict[str, dict] = {}
    if args.by_suite:
        suite_groups: dict[str, list[dict]] = {}
        for tm in task_metrics:
            suite = tm["benchmark"]
            suite_groups.setdefault(suite, []).append(tm)
        for suite, group in sorted(suite_groups.items()):
            by_suite[suite] = aggregate_metrics(group)

    # By-config aggregates
    by_config: dict[str, dict] = {}
    if args.by_config:
        config_groups: dict[str, list[dict]] = {}
        for tm in task_metrics:
            cfg = tm["config_name"]
            config_groups.setdefault(cfg, []).append(tm)
        for cfg, group in sorted(config_groups.items()):
            by_config[cfg] = aggregate_metrics(group)

    output = {
        "total_event_files": len(event_files),
        "computable_tasks": len(task_metrics),
        "skipped_no_ground_truth": skipped_no_gt,
        "skipped_parse_error": skipped_parse_error,
        "overall": overall,
        "per_task": task_metrics,
    }
    if by_suite:
        output["by_suite"] = by_suite
    if by_config:
        output["by_config"] = by_config

    json_str = json.dumps(output, indent=2) + "\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json_str)
        print(f"Written to {args.output}")
    else:
        print(json_str)

    # Summary to stderr
    print(f"\nProcessed {len(event_files)} event files: {len(task_metrics)} computable, "
          f"{skipped_no_gt} skipped (no GT), {skipped_parse_error} parse errors",
          file=sys.stderr)
    if task_metrics:
        print(f"  file_recall: mean={overall['file_recall']['mean']:.4f} "
              f"median={overall['file_recall']['median']:.4f}",
              file=sys.stderr)
        print(f"  MRR: mean={overall['mrr']['mean']:.4f} "
              f"median={overall['mrr']['median']:.4f}",
              file=sys.stderr)
        print(f"  MAP: mean={overall['map_score']['mean']:.4f} "
              f"median={overall['map_score']['median']:.4f}",
              file=sys.stderr)


if __name__ == "__main__":
    main()
