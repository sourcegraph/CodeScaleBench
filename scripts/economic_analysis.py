#!/usr/bin/env python3
"""Economic analysis engine for CodeScaleBench enterprise metrics.

Computes cost-per-successful-outcome, productivity-per-dollar, ROI metrics,
and comparative cost analysis across agent configurations.

All cost figures are hypothetical API costs (subscription accounts mean actual
spend is $0). See docs/WORKFLOW_METRICS.md for methodology context.

Usage:
    python3 scripts/economic_analysis.py
    python3 scripts/economic_analysis.py --help
    python3 scripts/economic_analysis.py --suite ccb_pytorch
    python3 scripts/economic_analysis.py --compare
    python3 scripts/economic_analysis.py --output economic_metrics.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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
from cost_report import extract_cost_data

logger = logging.getLogger(__name__)


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


def _extract_cost_from_task_metrics(task_dir: Path) -> Optional[float]:
    """Try to read cost_usd directly from task_metrics.json."""
    metrics_path = task_dir / "task_metrics.json"
    if not metrics_path.is_file():
        return None
    try:
        data = json.loads(metrics_path.read_text())
        cost = data.get("cost_usd")
        if cost is not None:
            return float(cost)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return None


def _extract_tokens_from_task_metrics(task_dir: Path) -> Optional[dict]:
    """Try to read token counts from task_metrics.json."""
    metrics_path = task_dir / "task_metrics.json"
    if not metrics_path.is_file():
        return None
    try:
        data = json.loads(metrics_path.read_text())
        inp = data.get("input_tokens")
        out = data.get("output_tokens")
        if inp is not None and out is not None:
            return {
                "input_tokens": inp,
                "output_tokens": out,
                "cache_creation_tokens": data.get("cache_creation_tokens"),
                "cache_read_tokens": data.get("cache_read_tokens"),
            }
    except (OSError, json.JSONDecodeError):
        pass
    return None


def extract_economic_record(task_dir: Path, suite: str, config: str) -> Optional[dict]:
    """Extract economic metrics for a single task.

    Returns a dict with cost, reward, and derived metrics, or None if
    the task directory lacks usable data.
    """
    result_path = task_dir / "result.json"
    if not result_path.is_file():
        return None

    try:
        result_data = json.loads(result_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    # Skip batch-level result.json
    if "n_total_trials" in result_data and "task_name" not in result_data:
        return None

    task_name = _extract_task_name(task_dir.name)
    reward = _extract_reward(result_data)

    # Cost: prefer task_metrics.json (corrected extraction), fall back to cost_report.py
    cost_usd = _extract_cost_from_task_metrics(task_dir)
    total_tokens = None

    if cost_usd is None:
        cost_data = extract_cost_data(task_dir)
        if cost_data:
            cost_usd = cost_data.get("cost_usd")

    # Token counts for efficiency metric
    token_data = _extract_tokens_from_task_metrics(task_dir)
    if token_data:
        total_tokens = (token_data.get("input_tokens") or 0) + (token_data.get("output_tokens") or 0)
    else:
        cost_data = extract_cost_data(task_dir)
        if cost_data:
            total_tokens = (cost_data.get("input_tokens") or 0) + (cost_data.get("output_tokens") or 0)

    if cost_usd is None:
        return None

    # Determine status
    passed = reward is not None and reward > 0
    cost_per_success = cost_usd / reward if passed and reward and reward > 0 else None

    return {
        "task_name": task_name,
        "suite": suite,
        "config": config,
        "cost_usd": round(cost_usd, 6),
        "reward": reward,
        "passed": passed,
        "cost_per_success": round(cost_per_success, 4) if cost_per_success is not None else None,
        "total_tokens": total_tokens,
    }


# ---------------------------------------------------------------------------
# Scanning & dedup
# ---------------------------------------------------------------------------

def scan_economic_data(
    suite_filter: Optional[str] = None,
    config_filter: Optional[str] = None,
) -> list[dict]:
    """Scan runs/official/ and extract economic data for all tasks.

    Uses timestamp-based dedup: for duplicate (suite, config, task_name),
    keeps the latest started_at.
    """
    if not RUNS_DIR.exists():
        logger.warning("runs/official/ not found: %s", RUNS_DIR)
        return []

    raw_records: list[tuple[str, dict]] = []  # (started_at, record)

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
                record = extract_economic_record(task_dir, suite, config)
                if record is None:
                    continue

                # Get started_at for dedup
                started_at = ""
                result_path = task_dir / "result.json"
                try:
                    rdata = json.loads(result_path.read_text())
                    started_at = rdata.get("started_at", "")
                except (OSError, json.JSONDecodeError):
                    pass

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
# Per-config aggregates
# ---------------------------------------------------------------------------

def compute_per_config(tasks: list[dict]) -> dict[str, dict]:
    """Compute per-config aggregated economics.

    Returns {config: {total_cost, avg_cost_per_task, ...}}.
    """
    grouped: dict[str, list[dict]] = defaultdict(list)
    for t in tasks:
        grouped[t["config"]].append(t)

    result: dict[str, dict] = {}
    for config in CONFIGS:
        if config not in grouped:
            continue
        config_tasks = grouped[config]
        total_cost = sum(t["cost_usd"] for t in config_tasks)
        n_tasks = len(config_tasks)
        tasks_passed = sum(1 for t in config_tasks if t["passed"])
        total_tokens = sum(t["total_tokens"] for t in config_tasks if t["total_tokens"])

        avg_cost_per_task = total_cost / n_tasks if n_tasks > 0 else 0.0
        avg_cost_per_success = total_cost / tasks_passed if tasks_passed > 0 else None
        pass_rate = tasks_passed / n_tasks if n_tasks > 0 else 0.0
        productivity_per_dollar = tasks_passed / total_cost if total_cost > 0 else None
        token_efficiency = total_tokens / tasks_passed if tasks_passed > 0 and total_tokens else None

        result[config] = {
            "n_tasks": n_tasks,
            "total_cost_usd": round(total_cost, 4),
            "avg_cost_per_task_usd": round(avg_cost_per_task, 4),
            "avg_cost_per_success_usd": round(avg_cost_per_success, 4) if avg_cost_per_success is not None else None,
            "tasks_passed": tasks_passed,
            "pass_rate": round(pass_rate, 4),
            "productivity_per_dollar": round(productivity_per_dollar, 4) if productivity_per_dollar is not None else None,
            "token_efficiency": round(token_efficiency, 0) if token_efficiency is not None else None,
            "total_tokens": total_tokens,
        }

    return result


# ---------------------------------------------------------------------------
# Cost comparison (--compare mode)
# ---------------------------------------------------------------------------

def compute_cost_comparison(tasks: list[dict]) -> list[dict]:
    """Categorize each task by cost effectiveness across configs.

    Categories:
      - cost_effective: lower/same cost + same/better outcome
      - premium: higher cost + better outcome
      - waste: higher cost + same/worse outcome
      - no_comparison: task in only one config
    """
    # Group by (suite, task_name)
    by_task: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
    for t in tasks:
        by_task[(t["suite"], t["task_name"])][t["config"]] = t

    comparisons = []
    for (suite, task_name), configs in sorted(by_task.items()):
        bl = configs.get("baseline")
        sg = configs.get("sourcegraph_full")

        if not bl or not sg:
            # Only available in one config
            for config, t in configs.items():
                comparisons.append({
                    "task_name": task_name,
                    "suite": suite,
                    "category": "no_comparison",
                    "baseline_cost_usd": bl["cost_usd"] if bl else None,
                    "sg_full_cost_usd": sg["cost_usd"] if sg else None,
                    "baseline_passed": bl["passed"] if bl else None,
                    "sg_full_passed": sg["passed"] if sg else None,
                    "marginal_cost_usd": None,
                })
            continue

        marginal_cost = round(sg["cost_usd"] - bl["cost_usd"], 6)
        cost_higher = sg["cost_usd"] > bl["cost_usd"] * 1.05  # 5% tolerance
        outcome_better = sg["passed"] and not bl["passed"]
        outcome_same_or_better = sg["passed"] >= bl["passed"]

        if not cost_higher and outcome_same_or_better:
            category = "cost_effective"
        elif cost_higher and outcome_better:
            category = "premium"
        elif cost_higher and not outcome_better:
            category = "waste"
        else:
            # Cost lower but outcome worse — edge case
            category = "cost_effective"  # Still saving money

        comparisons.append({
            "task_name": task_name,
            "suite": suite,
            "category": category,
            "baseline_cost_usd": round(bl["cost_usd"], 6),
            "sg_full_cost_usd": round(sg["cost_usd"], 6),
            "baseline_passed": bl["passed"],
            "sg_full_passed": sg["passed"],
            "marginal_cost_usd": marginal_cost,
        })

    return comparisons


# ---------------------------------------------------------------------------
# ROI summary
# ---------------------------------------------------------------------------

def compute_roi_summary(
    per_config: dict[str, dict],
    cost_comparison: list[dict],
) -> dict[str, Any]:
    """Compute ROI summary metrics.

    Includes cost_delta_pct, pass_rate_delta, break_even_hours,
    and implied_hours_saved_per_dollar.
    """
    bl = per_config.get("baseline", {})
    sg = per_config.get("sourcegraph_full", {})

    bl_avg_cost = bl.get("avg_cost_per_task_usd", 0)
    sg_avg_cost = sg.get("avg_cost_per_task_usd", 0)
    bl_pass_rate = bl.get("pass_rate", 0)
    sg_pass_rate = sg.get("pass_rate", 0)

    # Cost delta percentage
    cost_delta_pct = None
    if bl_avg_cost > 0:
        cost_delta_pct = round(((sg_avg_cost - bl_avg_cost) / bl_avg_cost) * 100, 2)

    pass_rate_delta = round(sg_pass_rate - bl_pass_rate, 4) if sg and bl else None

    # Break-even hours: how many engineer-hours must be saved per dollar of
    # MCP cost for positive ROI.  marginal_cost / (value_of_hour) = break_even
    # We compute: total marginal cost / number of additional passes
    total_marginal = sum(
        c["marginal_cost_usd"]
        for c in cost_comparison
        if c["marginal_cost_usd"] is not None and c["category"] != "no_comparison"
    )
    additional_passes = sum(
        1 for c in cost_comparison
        if c.get("sg_full_passed") and not c.get("baseline_passed")
    )

    # Using average engineer hourly cost of $75/hr as reference
    engineer_hourly_cost = 75.0
    break_even_hours = None
    if total_marginal > 0:
        break_even_hours = round(total_marginal / engineer_hourly_cost, 4)

    # Implied hours saved per dollar: use workflow taxonomy average time multiplier
    # Conservative estimate: each additional pass saves ~30 min of engineer time
    avg_minutes_per_resolved = 30.0  # conservative modeled estimate
    total_hours_saved = (additional_passes * avg_minutes_per_resolved) / 60.0
    implied_hours_per_dollar = None
    if total_marginal > 0:
        implied_hours_per_dollar = round(total_hours_saved / total_marginal, 4)

    # Comparison category counts
    category_counts: dict[str, int] = defaultdict(int)
    for c in cost_comparison:
        category_counts[c["category"]] += 1

    return {
        "baseline_avg_cost_usd": bl_avg_cost,
        "sg_full_avg_cost_usd": sg_avg_cost,
        "cost_delta_pct": cost_delta_pct,
        "baseline_pass_rate": bl_pass_rate,
        "sg_full_pass_rate": sg_pass_rate,
        "pass_rate_delta": pass_rate_delta,
        "additional_passes_from_context": additional_passes,
        "total_marginal_cost_usd": round(total_marginal, 4),
        "break_even_hours": break_even_hours,
        "implied_hours_saved_per_dollar": implied_hours_per_dollar,
        "comparison_category_counts": dict(category_counts),
        "note": (
            "All cost figures are hypothetical API costs (subscription accounts "
            "mean actual spend is $0). Break-even and hours-saved are MODELED "
            "ESTIMATES. See docs/WORKFLOW_METRICS.md for methodology."
        ),
    }


# ---------------------------------------------------------------------------
# Output assembly
# ---------------------------------------------------------------------------

def build_output(
    tasks: list[dict],
    per_config: dict[str, dict],
    cost_comparison: list[dict],
    roi_summary: dict[str, Any],
    include_comparison: bool = False,
) -> dict:
    """Assemble the full economic_metrics.json output."""
    output: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology": (
            "Cost figures are hypothetical API costs computed from per-message "
            "token counts in claude-code.txt transcripts. Pricing: input $15/MTok, "
            "output $75/MTok, cache_write $18.75/MTok, cache_read $1.50/MTok. "
            "Subscription accounts mean actual spend is $0. ROI metrics are "
            "MODELED ESTIMATES."
        ),
        "per_task": tasks,
        "per_config": per_config,
        "roi_summary": roi_summary,
    }
    if include_comparison:
        output["cost_comparison"] = cost_comparison
    return output


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Economic analysis engine for CodeScaleBench enterprise metrics."
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
        "--compare", action="store_true",
        help="Include per-task cost comparison across configs",
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

    # Scan
    tasks = scan_economic_data(
        suite_filter=args.suite,
        config_filter=args.config,
    )

    if not tasks:
        logger.warning("No tasks found in %s", RUNS_DIR)

    # Aggregates
    per_config = compute_per_config(tasks)
    cost_comparison = compute_cost_comparison(tasks)
    roi_summary = compute_roi_summary(per_config, cost_comparison)

    # Build output
    output = build_output(
        tasks, per_config, cost_comparison, roi_summary,
        include_comparison=args.compare,
    )

    # Write
    json_str = json.dumps(output, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json_str + "\n")
        print(f"Wrote {len(tasks)} task records to {args.output}")
    else:
        print(json_str)


if __name__ == "__main__":
    main()
