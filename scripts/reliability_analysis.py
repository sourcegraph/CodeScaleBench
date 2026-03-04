#!/usr/bin/env python3
"""Reliability analysis pipeline for CodeScaleBench enterprise metrics.

Computes performance variance, confidence intervals (via bootstrap resampling),
cross-suite consistency, reliability floors, and failure clustering.

Usage:
    python3 scripts/reliability_analysis.py
    python3 scripts/reliability_analysis.py --help
    python3 scripts/reliability_analysis.py --suite ccb_pytorch --config baseline
    python3 scripts/reliability_analysis.py --output reliability_metrics.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

# Ensure scripts/ is on path for sibling imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from aggregate_status import (
    RUNS_DIR,
    CONFIGS,
    should_skip,
    detect_suite,
    _iter_task_dirs,
    _extract_task_name,
)

logger = logging.getLogger(__name__)

SELECTION_CONFIG = Path(__file__).resolve().parent.parent / "configs" / "selected_benchmark_tasks.json"

BOOTSTRAP_N_SAMPLES = 1000
BOOTSTRAP_SEED = 42


# ---------------------------------------------------------------------------
# Task metadata loading
# ---------------------------------------------------------------------------

def load_task_metadata() -> dict[str, dict]:
    """Load task metadata from selected_benchmark_tasks.json.

    Returns {task_id: {language, difficulty, mcp_benefit_score, benchmark, ...}}.
    """
    if not SELECTION_CONFIG.is_file():
        logger.warning("Selection config not found: %s", SELECTION_CONFIG)
        return {}
    try:
        data = json.loads(SELECTION_CONFIG.read_text())
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to parse selection config")
        return {}

    result = {}
    for t in data.get("tasks", []):
        task_id = t.get("task_id", "")
        if task_id:
            result[task_id] = t
    return result


def _match_task_to_metadata(task_name: str, metadata: dict[str, dict]) -> Optional[dict]:
    """Match a run task_name to metadata by prefix matching."""
    if task_name in metadata:
        return metadata[task_name]
    # Try stripping ccb_ prefix
    for meta_id, meta in metadata.items():
        if meta_id.startswith(task_name) or task_name.startswith(meta_id):
            return meta
        # Strip ccb_{benchmark}- prefix
        if meta_id.startswith(("ccb_", "csb_")):
            stripped = meta_id[4:]
            if stripped.startswith(task_name) or task_name.startswith(stripped):
                return meta
    return None


# ---------------------------------------------------------------------------
# Per-task extraction
# ---------------------------------------------------------------------------

def _extract_reward(result_data: dict) -> Optional[float]:
    """Extract reward from result.json data."""
    verifier = result_data.get("verifier_result") or {}
    rewards = verifier.get("rewards") or {}
    for key in ("reward", "score"):
        if key in rewards:
            try:
                return float(rewards[key])
            except (TypeError, ValueError):
                continue
    return None


def scan_task_rewards(
    suite_filter: Optional[str] = None,
    config_filter: Optional[str] = None,
) -> list[dict]:
    """Scan runs/official/ and extract reward for all tasks.

    Uses timestamp-based dedup: for duplicate (suite, config, task_name),
    keeps the latest started_at.
    """
    if not RUNS_DIR.exists():
        logger.warning("runs/official/ not found: %s", RUNS_DIR)
        return []

    raw_records: list[tuple[str, dict]] = []

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir() or should_skip(run_dir.name):
            continue
        suite = detect_suite(run_dir.name)
        if suite is None:
            continue
        if suite_filter and suite != suite_filter:
            continue

        for config in CONFIGS:
            if config_filter and config != config_filter:
                continue
            config_path = run_dir / config
            if not config_path.is_dir():
                continue

            for task_dir in _iter_task_dirs(config_path):
                result_path = task_dir / "result.json"
                if not result_path.is_file():
                    continue

                try:
                    result_data = json.loads(result_path.read_text())
                except (OSError, json.JSONDecodeError):
                    continue

                # Skip batch-level result.json
                if "n_total_trials" in result_data and "task_name" not in result_data:
                    continue

                task_name = _extract_task_name(task_dir.name)
                reward = _extract_reward(result_data)

                # Check for exception (errored tasks)
                has_exception = result_data.get("exception_info") is not None

                started_at = result_data.get("started_at", "")

                record = {
                    "task_name": task_name,
                    "suite": suite,
                    "config": config,
                    "reward": reward,
                    "has_exception": has_exception,
                }

                raw_records.append((started_at, record))

    # Timestamp-based dedup: latest wins
    best: dict[tuple[str, str, str], tuple[str, dict]] = {}
    for started_at, rec in raw_records:
        key = (rec["suite"], rec["config"], rec["task_name"])
        existing = best.get(key)
        if existing is None or started_at > existing[0]:
            best[key] = (started_at, rec)

    return [rec for _, rec in best.values()]


# ---------------------------------------------------------------------------
# Bootstrap confidence intervals
# ---------------------------------------------------------------------------

def bootstrap_ci(
    rewards: list[float],
    n_samples: int = BOOTSTRAP_N_SAMPLES,
    ci_level: float = 0.95,
    seed: int = BOOTSTRAP_SEED,
) -> dict:
    """Compute bootstrap confidence interval for pass rate.

    Args:
        rewards: list of 0.0/1.0 reward values
        n_samples: number of bootstrap resamples
        ci_level: confidence level (default 0.95)
        seed: random seed for reproducibility

    Returns dict with: pass_rate, ci_lower, ci_upper, n_tasks, ci_note
    """
    n = len(rewards)
    if n == 0:
        return {
            "pass_rate": None,
            "ci_lower": None,
            "ci_upper": None,
            "n_tasks": 0,
            "ci_note": "no data",
        }

    arr = np.array(rewards, dtype=float)
    point_estimate = float(np.mean(arr))

    if n < 5:
        return {
            "pass_rate": round(point_estimate, 4),
            "ci_lower": None,
            "ci_upper": None,
            "n_tasks": n,
            "ci_note": "insufficient data for CI (n < 5)",
        }

    rng = np.random.default_rng(seed)
    boot_means = np.empty(n_samples)
    for i in range(n_samples):
        sample = rng.choice(arr, size=n, replace=True)
        boot_means[i] = np.mean(sample)

    alpha = 1 - ci_level
    ci_lower = float(np.percentile(boot_means, 100 * alpha / 2))
    ci_upper = float(np.percentile(boot_means, 100 * (1 - alpha / 2)))

    return {
        "pass_rate": round(point_estimate, 4),
        "ci_lower": round(ci_lower, 4),
        "ci_upper": round(ci_upper, 4),
        "n_tasks": n,
        "ci_note": None,
    }


# ---------------------------------------------------------------------------
# Per-suite/config stats
# ---------------------------------------------------------------------------

def compute_per_suite_config_stats(tasks: list[dict]) -> dict[str, dict]:
    """Group tasks by (suite, config) and compute descriptive stats + CI.

    Returns {suite: {config: {mean_reward, std_dev, min, max, median, n_tasks, ci}}}.
    """
    grouped: dict[tuple[str, str], list[float]] = defaultdict(list)
    for t in tasks:
        reward = t.get("reward")
        if reward is not None:
            grouped[(t["suite"], t["config"])].append(reward)

    result: dict[str, dict] = {}
    for (suite, config), rewards in sorted(grouped.items()):
        if suite not in result:
            result[suite] = {}

        arr = np.array(rewards, dtype=float)
        n = len(arr)

        stats = {
            "n_tasks": n,
            "mean_reward": round(float(np.mean(arr)), 4),
            "std_dev": round(float(np.std(arr, ddof=1)), 4) if n > 1 else 0.0,
            "min": round(float(np.min(arr)), 4),
            "max": round(float(np.max(arr)), 4),
            "median": round(float(np.median(arr)), 4),
        }

        # Bootstrap CI
        ci = bootstrap_ci(rewards)
        stats["ci_95_lower"] = ci["ci_lower"]
        stats["ci_95_upper"] = ci["ci_upper"]
        stats["ci_note"] = ci["ci_note"]

        result[suite][config] = stats

    return result


# ---------------------------------------------------------------------------
# Cross-suite consistency
# ---------------------------------------------------------------------------

def compute_cross_suite_consistency(per_suite_config: dict[str, dict]) -> dict[str, dict]:
    """Compute coefficient of variation of per-suite pass rates within each config.

    Returns {config: {cv, mean_pass_rate, std_pass_rate, per_suite_rates}}.
    """
    # Collect per-suite pass rates for each config
    config_rates: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for suite, configs in per_suite_config.items():
        for config, stats in configs.items():
            if stats["n_tasks"] > 0:
                config_rates[config].append((suite, stats["mean_reward"]))

    result: dict[str, dict] = {}
    for config, rates in sorted(config_rates.items()):
        values = [r for _, r in rates]
        arr = np.array(values, dtype=float)
        mean_rate = float(np.mean(arr))
        std_rate = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
        cv = std_rate / mean_rate if mean_rate > 0 else None

        result[config] = {
            "coefficient_of_variation": round(cv, 4) if cv is not None else None,
            "mean_pass_rate": round(mean_rate, 4),
            "std_pass_rate": round(std_rate, 4),
            "n_suites": len(rates),
            "per_suite_rates": {s: round(r, 4) for s, r in rates},
        }

    return result


# ---------------------------------------------------------------------------
# Reliability floor
# ---------------------------------------------------------------------------

def compute_reliability_floor(per_suite_config: dict[str, dict]) -> dict[str, dict]:
    """Compute per-config reliability_floor = mean_reward - 2 * std_dev.

    This is a pessimistic estimate of worst-case expected performance.
    Returns {config: {reliability_floor, mean_reward, std_dev}}.
    """
    # Aggregate all rewards by config
    config_rewards: dict[str, list[float]] = defaultdict(list)
    for suite, configs in per_suite_config.items():
        for config, stats in configs.items():
            # We need the actual mean and std across all tasks in this config
            # We can compute from the per-suite stats, weighted by n_tasks
            config_rewards[config].append(
                (stats["mean_reward"], stats["std_dev"], stats["n_tasks"])
            )

    result: dict[str, dict] = {}
    for config, suite_stats in sorted(config_rewards.items()):
        # Weighted mean across suites
        total_n = sum(n for _, _, n in suite_stats)
        if total_n == 0:
            continue
        weighted_mean = sum(m * n for m, _, n in suite_stats) / total_n
        # Pooled std dev
        weighted_var = sum(((s ** 2) * (n - 1) if n > 1 else 0) for _, s, n in suite_stats)
        pooled_std = (weighted_var / max(total_n - len(suite_stats), 1)) ** 0.5

        floor = weighted_mean - 2 * pooled_std

        result[config] = {
            "reliability_floor": round(max(floor, 0.0), 4),
            "mean_reward": round(weighted_mean, 4),
            "std_dev": round(pooled_std, 4),
            "n_tasks": total_n,
        }

    return result


# ---------------------------------------------------------------------------
# Failure clustering
# ---------------------------------------------------------------------------

def _assign_mcp_quartile(score: Optional[float]) -> str:
    """Assign mcp_benefit_score to a quartile label."""
    if score is None:
        return "unknown"
    if score < 0.25:
        return "Q1 (0.00-0.25)"
    elif score < 0.50:
        return "Q2 (0.25-0.50)"
    elif score < 0.75:
        return "Q3 (0.50-0.75)"
    else:
        return "Q4 (0.75-1.00)"


def compute_failure_clusters(
    tasks: list[dict],
    metadata: dict[str, dict],
) -> list[dict]:
    """Group failed tasks by language, difficulty, suite, and MCP benefit quartile.

    Flags groups with failure_rate > 2x overall average as failure clusters.
    Returns list of cluster records.
    """
    # Enrich tasks with metadata
    enriched = []
    for t in tasks:
        meta = _match_task_to_metadata(t["task_name"], metadata)
        enriched.append({
            **t,
            "language": (meta or {}).get("language", "unknown"),
            "difficulty": (meta or {}).get("difficulty", "unknown"),
            "mcp_benefit_score": (meta or {}).get("mcp_benefit_score"),
            "mcp_quartile": _assign_mcp_quartile(
                (meta or {}).get("mcp_benefit_score")
            ),
        })

    # Overall failure rate
    total = len(enriched)
    if total == 0:
        return []
    failed = sum(1 for t in enriched if t.get("reward") is not None and t["reward"] == 0.0)
    overall_failure_rate = failed / total if total > 0 else 0.0

    if overall_failure_rate == 0:
        return []

    # Grouping dimensions
    dimensions = {
        "language": lambda t: t["language"],
        "difficulty": lambda t: t["difficulty"],
        "benchmark_suite": lambda t: t["suite"],
        "mcp_benefit_score_quartile": lambda t: t["mcp_quartile"],
    }

    clusters = []
    for dim_name, key_fn in dimensions.items():
        groups: dict[str, dict] = defaultdict(lambda: {"total": 0, "failed": 0})
        for t in enriched:
            group_key = key_fn(t)
            groups[group_key]["total"] += 1
            if t.get("reward") is not None and t["reward"] == 0.0:
                groups[group_key]["failed"] += 1

        for group, counts in sorted(groups.items()):
            if counts["total"] < 2:
                continue
            group_failure_rate = counts["failed"] / counts["total"]
            relative_rate = group_failure_rate / overall_failure_rate if overall_failure_rate > 0 else 0.0

            is_cluster = relative_rate > 2.0

            description = (
                f"{group} tasks fail {relative_rate:.1f}x more often than average "
                f"({group_failure_rate * 100:.0f}% vs {overall_failure_rate * 100:.0f}%)"
            )

            cluster_record = {
                "dimension": dim_name,
                "group": group,
                "n_tasks": counts["total"],
                "n_failed": counts["failed"],
                "failure_rate": round(group_failure_rate, 4),
                "overall_failure_rate": round(overall_failure_rate, 4),
                "relative_rate": round(relative_rate, 2),
                "is_failure_cluster": is_cluster,
                "description": description,
            }
            if is_cluster:
                clusters.append(cluster_record)

    return clusters


# ---------------------------------------------------------------------------
# Output assembly
# ---------------------------------------------------------------------------

def build_output(
    per_suite_config: dict[str, dict],
    cross_suite_consistency: dict[str, dict],
    reliability_floor: dict[str, dict],
    failure_clusters: list[dict],
) -> dict:
    """Assemble the full reliability_metrics.json output."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "per_suite_config": per_suite_config,
        "cross_suite_consistency": cross_suite_consistency,
        "reliability_floor": reliability_floor,
        "failure_clusters": failure_clusters,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reliability analysis pipeline: variance, CI, and failure clustering."
    )
    parser.add_argument(
        "--suite", default=None,
        help="Filter to one benchmark suite (e.g., ccb_pytorch)",
    )
    parser.add_argument(
        "--config", default=None,
        help="Filter to one config (baseline, sourcegraph_full)",
    )
    parser.add_argument(
        "--output", default=None, metavar="FILE",
        help="Write JSON output to FILE (default: stdout)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    # Load task metadata for failure clustering
    metadata = load_task_metadata()

    # Scan
    tasks = scan_task_rewards(
        suite_filter=args.suite,
        config_filter=args.config,
    )

    if not tasks:
        logger.warning("No tasks found in %s", RUNS_DIR)

    # Compute stats
    per_suite_config = compute_per_suite_config_stats(tasks)
    cross_suite = compute_cross_suite_consistency(per_suite_config)
    rel_floor = compute_reliability_floor(per_suite_config)
    clusters = compute_failure_clusters(tasks, metadata)

    # Build output
    output = build_output(per_suite_config, cross_suite, rel_floor, clusters)

    # Write
    json_str = json.dumps(output, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json_str + "\n")
        print(f"Wrote reliability metrics to {args.output}")
    else:
        print(json_str)


if __name__ == "__main__":
    main()
