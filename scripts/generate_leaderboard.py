#!/usr/bin/env python3
"""
Generate leaderboard views from MANIFEST.json.

Reads runs/official/MANIFEST.json and produces:
  - leaderboard.json: machine-readable per-benchmark and aggregate rankings
  - LEADERBOARD_RESULTS.md: human-readable ranking tables

Scoring rules (see docs/LEADERBOARD.md):
  - Per-benchmark: mean_reward across all tasks
  - Aggregate: unweighted mean of per-benchmark mean_rewards (all 13 required)
  - Errored tasks count as reward=0.0
  - Must run ALL tasks in a benchmark to qualify for that benchmark's leaderboard
  - Tie-breaking: pass_rate > median_reward > token_efficiency
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "runs" / "official" / "MANIFEST.json"
SELECTED_TASKS_PATH = PROJECT_ROOT / "configs" / "selected_benchmark_tasks.json"

# Required task counts per benchmark (from selected_benchmark_tasks.json)
# Loaded dynamically in main(), but fallback defaults here for reference
DEFAULT_BENCHMARK_TASK_COUNTS = {
    "ccb_swebenchpro": 36,
    "ccb_dependeval": 32,
    "ccb_locobench": 25,
    "ccb_pytorch": 12,
    "ccb_repoqa": 10,
    "ccb_dibench": 8,
    "ccb_tac": 8,
    "ccb_k8sdocs": 5,
    "ccb_crossrepo": 5,
    "ccb_linuxflbench": 5,
    "ccb_largerepo": 4,
    "ccb_codereview": 3,
    "ccb_sweperf": 3,
}

TOTAL_BENCHMARKS = 13


def load_benchmark_task_counts() -> dict[str, int]:
    """Load required task counts per benchmark from selected_benchmark_tasks.json."""
    if not SELECTED_TASKS_PATH.exists():
        print(f"Warning: {SELECTED_TASKS_PATH} not found, using defaults", file=sys.stderr)
        return dict(DEFAULT_BENCHMARK_TASK_COUNTS)

    data = json.loads(SELECTED_TASKS_PATH.read_text())
    tasks = data.get("tasks", [])
    counts: dict[str, int] = defaultdict(int)
    for task in tasks:
        benchmark = task.get("benchmark", "")
        if benchmark:
            counts[benchmark] += 1
    return dict(counts) if counts else dict(DEFAULT_BENCHMARK_TASK_COUNTS)


def compute_pass_rate(tasks: dict) -> float:
    """Fraction of tasks with reward > 0.0."""
    if not tasks:
        return 0.0
    passed = sum(1 for t in tasks.values() if t.get("reward", 0.0) > 0.0)
    return round(passed / len(tasks), 4)


def compute_median_reward(tasks: dict) -> float:
    """Median of per-task rewards."""
    rewards = sorted(t.get("reward", 0.0) for t in tasks.values())
    n = len(rewards)
    if n == 0:
        return 0.0
    if n % 2 == 1:
        return rewards[n // 2]
    return (rewards[n // 2 - 1] + rewards[n // 2]) / 2.0


def generate_leaderboard(manifest: dict, benchmark_task_counts: dict) -> dict:
    """Generate leaderboard data from MANIFEST.

    Returns dict with 'per_benchmark' and 'aggregate' arrays.
    """
    runs = manifest.get("runs", {})

    # Group by (agent_model, config) -> {benchmark: run_data}
    # Each MANIFEST key is "suite/config"
    agent_benchmarks: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)

    for manifest_key, run_data in runs.items():
        parts = manifest_key.split("/")
        if len(parts) != 2:
            continue
        benchmark, config = parts
        model = run_data.get("model", "unknown")
        agent_benchmarks[(model, config)][benchmark] = run_data

    # Build per-benchmark leaderboard
    per_benchmark = []
    for (agent, config), benchmarks in sorted(agent_benchmarks.items()):
        for benchmark, run_data in sorted(benchmarks.items()):
            required = benchmark_task_counts.get(benchmark)
            actual = run_data.get("task_count", 0)
            is_complete = required is not None and actual >= required

            entry = {
                "benchmark": benchmark,
                "agent": agent,
                "config": config,
                "mean_reward": run_data.get("mean_reward", 0.0),
                "pass_rate": compute_pass_rate(run_data.get("tasks", {})),
                "task_count": actual,
                "required_tasks": required or actual,
                "is_complete": is_complete,
            }
            per_benchmark.append(entry)

    # Build aggregate leaderboard
    aggregate = []
    for (agent, config), benchmarks in sorted(agent_benchmarks.items()):
        # Check completeness: must have all 13 benchmarks with full task coverage
        complete_benchmarks = []
        for benchmark, run_data in benchmarks.items():
            required = benchmark_task_counts.get(benchmark)
            actual = run_data.get("task_count", 0)
            if required is not None and actual >= required:
                complete_benchmarks.append(benchmark)

        benchmarks_completed = len(complete_benchmarks)
        total_tasks = sum(r.get("task_count", 0) for r in benchmarks.values())

        # Aggregate score: mean of per-benchmark mean_rewards for COMPLETE benchmarks
        if complete_benchmarks:
            benchmark_means = [
                benchmarks[b].get("mean_reward", 0.0) for b in complete_benchmarks
            ]
            agg_score = round(sum(benchmark_means) / len(benchmark_means), 4)
        else:
            agg_score = 0.0

        # Total pass rate across all tasks
        all_tasks = {}
        for run_data in benchmarks.values():
            all_tasks.update(run_data.get("tasks", {}))
        total_pass_rate = compute_pass_rate(all_tasks)
        median_reward = compute_median_reward(all_tasks)

        entry = {
            "agent": agent,
            "config": config,
            "ccb_aggregate_score": agg_score,
            "benchmarks_completed": benchmarks_completed,
            "total_benchmarks": TOTAL_BENCHMARKS,
            "total_tasks": total_tasks,
            "all_benchmarks_complete": benchmarks_completed == TOTAL_BENCHMARKS,
            "pass_rate": total_pass_rate,
            "median_reward": round(median_reward, 4),
        }
        aggregate.append(entry)

    # Sort per-benchmark: by benchmark, then mean_reward desc, then tie-breakers
    per_benchmark.sort(
        key=lambda e: (e["benchmark"], -e["mean_reward"], -e["pass_rate"]),
    )

    # Sort aggregate: all-complete first, then by ccb_aggregate_score desc, tie-breakers
    aggregate.sort(
        key=lambda e: (
            -int(e["all_benchmarks_complete"]),
            -e["ccb_aggregate_score"],
            -e["pass_rate"],
            -e["median_reward"],
        ),
    )

    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "manifest_source": str(MANIFEST_PATH),
        "per_benchmark": per_benchmark,
        "aggregate": aggregate,
    }


def generate_markdown(leaderboard: dict, benchmark_task_counts: dict) -> str:
    """Generate LEADERBOARD_RESULTS.md content."""
    lines = [
        "# CodeContextBench Leaderboard Results",
        "",
        f"*Generated: {leaderboard['generated']}*",
        "",
    ]

    # Aggregate ranking
    lines.append("## Aggregate Ranking")
    lines.append("")
    agg = leaderboard["aggregate"]
    complete = [e for e in agg if e["all_benchmarks_complete"]]
    partial = [e for e in agg if not e["all_benchmarks_complete"]]

    if complete:
        lines.append("| Rank | Agent | Config | CCB Aggregate | Benchmarks | Tasks | Pass Rate |")
        lines.append("|------|-------|--------|--------------|------------|-------|-----------|")
        for i, entry in enumerate(complete, 1):
            lines.append(
                f"| {i} | {entry['agent']} | {entry['config']} | "
                f"{entry['ccb_aggregate_score']:.3f} | "
                f"{entry['benchmarks_completed']}/{entry['total_benchmarks']} | "
                f"{entry['total_tasks']} | {entry['pass_rate']:.3f} |"
            )
        lines.append("")
    else:
        lines.append("*No entries with complete coverage of all 13 benchmarks.*")
        lines.append("")

    if partial:
        lines.append("### Partial Coverage (not ranked in aggregate)")
        lines.append("")
        lines.append("| Agent | Config | Score (qualifying) | Benchmarks | Tasks | Pass Rate |")
        lines.append("|-------|--------|--------------------|------------|-------|-----------|")
        for entry in partial:
            lines.append(
                f"| {entry['agent']} | {entry['config']} | "
                f"{entry['ccb_aggregate_score']:.3f} | "
                f"{entry['benchmarks_completed']}/{entry['total_benchmarks']} | "
                f"{entry['total_tasks']} | {entry['pass_rate']:.3f} |"
            )
        lines.append("")

    # Per-benchmark rankings
    lines.append("## Per-Benchmark Rankings")
    lines.append("")

    # Group by benchmark
    by_benchmark: dict[str, list] = defaultdict(list)
    for entry in leaderboard["per_benchmark"]:
        by_benchmark[entry["benchmark"]].append(entry)

    for benchmark in sorted(by_benchmark.keys()):
        entries = by_benchmark[benchmark]
        required = benchmark_task_counts.get(benchmark, "?")
        lines.append(f"### {benchmark} ({required} tasks)")
        lines.append("")
        lines.append("| Rank | Agent | Config | Mean Reward | Pass Rate | Tasks | Complete |")
        lines.append("|------|-------|--------|-------------|-----------|-------|----------|")

        # Separate complete and incomplete
        complete_entries = [e for e in entries if e["is_complete"]]
        incomplete_entries = [e for e in entries if not e["is_complete"]]

        rank = 1
        for entry in complete_entries:
            lines.append(
                f"| {rank} | {entry['agent']} | {entry['config']} | "
                f"{entry['mean_reward']:.3f} | {entry['pass_rate']:.3f} | "
                f"{entry['task_count']}/{entry['required_tasks']} | Yes |"
            )
            rank += 1
        for entry in incomplete_entries:
            lines.append(
                f"| - | {entry['agent']} | {entry['config']} | "
                f"{entry['mean_reward']:.3f} | {entry['pass_rate']:.3f} | "
                f"{entry['task_count']}/{entry['required_tasks']} | No |"
            )
        lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append("*Scoring rules: see [docs/LEADERBOARD.md](docs/LEADERBOARD.md)*")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Generate leaderboard from MANIFEST.json",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=MANIFEST_PATH,
        help=f"Path to MANIFEST.json (default: {MANIFEST_PATH})",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=PROJECT_ROOT / "leaderboard.json",
        help="Output path for leaderboard JSON",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=PROJECT_ROOT / "LEADERBOARD_RESULTS.md",
        help="Output path for leaderboard Markdown",
    )
    args = parser.parse_args()

    if not args.manifest.exists():
        print(f"ERROR: MANIFEST not found: {args.manifest}", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(args.manifest.read_text())
    benchmark_task_counts = load_benchmark_task_counts()

    leaderboard = generate_leaderboard(manifest, benchmark_task_counts)

    # Write JSON
    with open(args.output_json, "w") as f:
        json.dump(leaderboard, f, indent=2)
    print(f"Wrote {args.output_json}")

    # Write Markdown
    md = generate_markdown(leaderboard, benchmark_task_counts)
    args.output_md.write_text(md)
    print(f"Wrote {args.output_md}")

    # Summary
    print(f"\nPer-benchmark entries: {len(leaderboard['per_benchmark'])}")
    print(f"Aggregate entries: {len(leaderboard['aggregate'])}")
    complete_agg = sum(1 for e in leaderboard["aggregate"] if e["all_benchmarks_complete"])
    print(f"  Complete (all 13 benchmarks): {complete_agg}")
    print(f"  Partial: {len(leaderboard['aggregate']) - complete_agg}")


if __name__ == "__main__":
    main()
