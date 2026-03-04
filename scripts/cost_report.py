#!/usr/bin/env python3
"""Token and cost analysis for benchmark runs.

Aggregates input/output tokens and estimated cost across tasks,
grouped by suite and config.

Usage:
    python3 scripts/cost_report.py
    python3 scripts/cost_report.py --suite ccb_pytorch
    python3 scripts/cost_report.py --format json
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config_utils import discover_configs, config_short_name
from aggregate_status import (
    RUNS_DIR, should_skip, detect_suite, _iter_task_dirs, _extract_task_name,
)

# Anthropic pricing (per token, as of 2025)
# Claude Opus 4.5
PRICING = {
    "input_per_token": 15.0 / 1_000_000,     # $15/MTok
    "output_per_token": 75.0 / 1_000_000,     # $75/MTok
    "cache_write_per_token": 18.75 / 1_000_000,  # $18.75/MTok
    "cache_read_per_token": 1.875 / 1_000_000,   # $1.875/MTok
}


def extract_cost_data(task_dir: Path) -> dict | None:
    """Extract token counts and cost from a task directory."""
    # Prefer task_metrics.json (richer data)
    metrics_path = task_dir / "task_metrics.json"
    result_path = task_dir / "result.json"

    data = {}

    if metrics_path.is_file():
        try:
            metrics = json.loads(metrics_path.read_text())
            data = {
                "input_tokens": metrics.get("input_tokens"),
                "output_tokens": metrics.get("output_tokens"),
                "cache_creation_tokens": metrics.get("cache_creation_tokens"),
                "cache_read_tokens": metrics.get("cache_read_tokens"),
                "cost_usd": metrics.get("cost_usd"),
                "wall_clock_seconds": metrics.get("wall_clock_seconds"),
                "reward": metrics.get("reward"),
                "status": metrics.get("status"),
            }
        except (json.JSONDecodeError, OSError):
            pass

    if not data.get("input_tokens") and result_path.is_file():
        try:
            result = json.loads(result_path.read_text())
            agent_result = result.get("agent_result") or {}
            data["input_tokens"] = agent_result.get("n_input_tokens")
            data["output_tokens"] = agent_result.get("n_output_tokens")
            data["wall_clock_seconds"] = result.get("wall_clock_seconds")

            # Extract reward
            vr = result.get("verifier_result") or {}
            rewards = vr.get("rewards") or {}
            data["reward"] = rewards.get("reward", rewards.get("score"))

            exc = result.get("exception_info")
            if exc:
                data["status"] = "errored"
            elif data["reward"] and data["reward"] > 0:
                data["status"] = "passed"
            else:
                data["status"] = "failed"
        except (json.JSONDecodeError, OSError):
            pass

    if not data.get("input_tokens"):
        return None

    # Estimate cost if not available
    if data.get("cost_usd") is None:
        inp = data.get("input_tokens") or 0
        out = data.get("output_tokens") or 0
        cache_w = data.get("cache_creation_tokens") or 0
        cache_r = data.get("cache_read_tokens") or 0

        cost = (
            inp * PRICING["input_per_token"]
            + out * PRICING["output_per_token"]
            + cache_w * PRICING["cache_write_per_token"]
            + cache_r * PRICING["cache_read_per_token"]
        )
        data["cost_usd"] = round(cost, 4)

    return data


def scan_costs(suite_filter: str | None = None, config_filter: str | None = None) -> dict:
    """Scan all tasks and aggregate cost data."""
    # per (suite, config) aggregation
    agg = defaultdict(lambda: {
        "tasks": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "cost_usd": 0.0,
        "wall_clock_seconds": 0.0,
        "passed": 0,
        "failed": 0,
        "errored": 0,
        "task_costs": [],
    })

    if not RUNS_DIR.exists():
        return _build_cost_output(agg)

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir() or should_skip(run_dir.name):
            continue
        suite = detect_suite(run_dir.name)
        if suite is None:
            continue
        if suite_filter and suite != suite_filter:
            continue

        for config in discover_configs(run_dir):
            if config_filter and config != config_filter:
                continue
            config_path = run_dir / config

            for task_dir in _iter_task_dirs(config_path):
                cost_data = extract_cost_data(task_dir)
                if cost_data is None:
                    continue

                key = (suite, config)
                a = agg[key]
                a["tasks"] += 1
                a["input_tokens"] += cost_data.get("input_tokens") or 0
                a["output_tokens"] += cost_data.get("output_tokens") or 0
                a["cost_usd"] += cost_data.get("cost_usd") or 0.0
                a["wall_clock_seconds"] += cost_data.get("wall_clock_seconds") or 0.0

                status = cost_data.get("status", "")
                if status == "passed":
                    a["passed"] += 1
                elif status == "errored":
                    a["errored"] += 1
                else:
                    a["failed"] += 1

                task_name = _extract_task_name(task_dir.name)
                a["task_costs"].append({
                    "task_name": task_name,
                    "input_tokens": cost_data.get("input_tokens") or 0,
                    "output_tokens": cost_data.get("output_tokens") or 0,
                    "cost_usd": cost_data.get("cost_usd") or 0.0,
                    "wall_clock_seconds": cost_data.get("wall_clock_seconds") or 0.0,
                    "status": status,
                })

    return _build_cost_output(agg)


def _build_cost_output(agg) -> dict:
    """Build cost report output."""
    total_cost = 0.0
    total_input = 0
    total_output = 0
    total_tasks = 0
    total_wall = 0.0

    by_suite = defaultdict(lambda: defaultdict(dict))

    for (suite, config), data in sorted(agg.items()):
        total_cost += data["cost_usd"]
        total_input += data["input_tokens"]
        total_output += data["output_tokens"]
        total_tasks += data["tasks"]
        total_wall += data["wall_clock_seconds"]

        # Sort task_costs by cost descending for "most expensive" view
        data["task_costs"].sort(key=lambda x: x["cost_usd"], reverse=True)

        by_suite[suite][config] = {
            "tasks": data["tasks"],
            "input_tokens": data["input_tokens"],
            "output_tokens": data["output_tokens"],
            "cost_usd": round(data["cost_usd"], 2),
            "wall_clock_hours": round(data["wall_clock_seconds"] / 3600, 2),
            "avg_cost_per_task": round(data["cost_usd"] / data["tasks"], 2) if data["tasks"] else 0,
            "passed": data["passed"],
            "top_expensive": data["task_costs"][:5],
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "tasks": total_tasks,
            "input_tokens": total_input,
            "output_tokens": total_output,
            "cost_usd": round(total_cost, 2),
            "wall_clock_hours": round(total_wall / 3600, 2),
            "avg_cost_per_task": round(total_cost / total_tasks, 2) if total_tasks else 0,
        },
        "by_suite": {s: dict(c) for s, c in sorted(by_suite.items())},
    }


def format_cost_table(data: dict) -> str:
    """Format cost report as ASCII table."""
    lines = []
    t = data["totals"]
    lines.append(f"Cost Report  (generated: {data['generated_at']})")
    lines.append("")
    lines.append(f"TOTALS: {t['tasks']} tasks, ${t['cost_usd']:.2f} USD, "
                 f"{t['input_tokens']:,} input + {t['output_tokens']:,} output tokens, "
                 f"{t['wall_clock_hours']:.1f} wall-clock hours")
    lines.append(f"  Avg cost per task: ${t['avg_cost_per_task']:.2f}")
    lines.append("")

    # Per suite/config
    header = f"{'Suite':25s} {'Config':18s}  {'Tasks':>5s}  {'Cost':>8s}  {'Avg/task':>8s}  {'Input tok':>12s}  {'Output tok':>12s}  {'Hours':>6s}"
    lines.append(header)
    lines.append("-" * len(header))

    for suite, configs in sorted(data["by_suite"].items()):
        for config in sorted(configs.keys()):
            c = configs[config]
            short_cfg = config_short_name(config)
            lines.append(
                f"{suite:25s} {short_cfg:18s}  {c['tasks']:>5d}  "
                f"${c['cost_usd']:>7.2f}  ${c['avg_cost_per_task']:>7.2f}  "
                f"{c['input_tokens']:>12,}  {c['output_tokens']:>12,}  "
                f"{c['wall_clock_hours']:>6.1f}"
            )
    lines.append("")

    # Config comparison
    config_costs = defaultdict(float)
    config_tasks = defaultdict(int)
    for suite, configs in data["by_suite"].items():
        for config, c in configs.items():
            config_costs[config] += c["cost_usd"]
            config_tasks[config] += c["tasks"]

    if len(config_costs) > 1:
        lines.append("CONFIG COST COMPARISON:")
        baseline_cost = config_costs.get("baseline", 0)
        for config in sorted(config_costs.keys()):
            cost = config_costs[config]
            tasks = config_tasks[config]
            short = config_short_name(config)
            diff = ""
            if baseline_cost > 0 and config != "baseline":
                pct = ((cost / tasks) / (baseline_cost / config_tasks.get("baseline", 1)) - 1) * 100
                diff = f" ({pct:+.0f}% vs baseline per task)"
            lines.append(f"  {short:18s}  ${cost:.2f} across {tasks} tasks{diff}")
        lines.append("")

    # Most expensive tasks overall
    all_tasks = []
    for suite, configs in data["by_suite"].items():
        for config, c in configs.items():
            for tc in c.get("top_expensive", []):
                tc["suite"] = suite
                tc["config"] = config
                all_tasks.append(tc)
    all_tasks.sort(key=lambda x: x["cost_usd"], reverse=True)

    if all_tasks:
        lines.append("MOST EXPENSIVE TASKS:")
        for tc in all_tasks[:10]:
            short_cfg = tc["config"].replace("sourcegraph_", "SG_")
            lines.append(
                f"  ${tc['cost_usd']:>7.2f}  {tc['suite']:20s}  {short_cfg:12s}  {tc['task_name']}"
            )

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Token and cost analysis for benchmark runs.")
    parser.add_argument("--format", choices=["table", "json"], default="table")
    parser.add_argument("--suite", default=None, help="Filter to one suite")
    parser.add_argument("--config", default=None, help="Filter to one config")
    args = parser.parse_args()

    data = scan_costs(suite_filter=args.suite, config_filter=args.config)

    if args.format == "json":
        print(json.dumps(data, indent=2))
    else:
        print(format_cost_table(data))


if __name__ == "__main__":
    main()
