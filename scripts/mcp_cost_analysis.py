#!/usr/bin/env python3
"""Analyze cost ratios for tasks where MCP tools were used 50%+ of total tool calls.

For each task that has BOTH a baseline run AND an SG_full run where MCP tools
were used >= 50% of total tool calls, compute the cost ratio (SG_full / baseline).

Reports per-task and per-suite averages.
"""

import json
import re
import sys
import statistics
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config_utils import is_config_dir

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs" / "official"

SKIP_PATTERNS = ["__broken_verifier", "validation_test", "archive", "__archived"]

DIR_PREFIX_TO_SUITE = {
    "bigcode_mcp_": "ccb_largerepo",
    "bigcode_sgcompare_": "ccb_largerepo",
    "codereview_": "ccb_codereview",
    "crossrepo_": "ccb_crossrepo",
    "dependeval_": "ccb_dependeval",
    "dibench_": "ccb_dibench",
    "enterprise_": "ccb_enterprise",
    "governance_": "ccb_governance",
    "investigation_": "ccb_investigation",
    "k8s_docs_": "ccb_k8sdocs",
    "linuxflbench_": "ccb_linuxflbench",
    "locobench_": "ccb_locobench",
    "pytorch_": "ccb_pytorch",
    "repoqa_": "ccb_repoqa",
    "swebenchpro_": "ccb_swebenchpro",
    "sweperf_": "ccb_sweperf",
    "tac_": "ccb_tac",
    "paired_rerun_dibench_": "ccb_dibench",
    "paired_rerun_crossrepo_": "ccb_crossrepo",
    "paired_rerun_pytorch_": "ccb_pytorch",
    "paired_rerun_": None,
}

# Archived suites — excluded from all analysis
ARCHIVED_SUITES = {"ccb_locobench", "ccb_repoqa", "ccb_dependeval"}

# Minimum agent execution seconds to consider a task valid
MIN_AGENT_TIME_SEC = 10

# Anthropic pricing (Opus 4.5)
PRICING = {
    "input_per_token": 15.0 / 1_000_000,
    "output_per_token": 75.0 / 1_000_000,
    "cache_write_per_token": 18.75 / 1_000_000,
    "cache_read_per_token": 1.875 / 1_000_000,
}


def should_skip(dirname: str) -> bool:
    return any(pat in dirname for pat in SKIP_PATTERNS)


def _is_batch_timestamp(name: str) -> bool:
    return bool(re.match(r"\d{4}-\d{2}-\d{2}__\d{2}-\d{2}-\d{2}", name))


def _suite_from_run_dir(name: str) -> str | None:
    for prefix, suite in DIR_PREFIX_TO_SUITE.items():
        if name.startswith(prefix):
            return suite
    if name.startswith("swebenchpro_gapfill_"):
        return "ccb_swebenchpro"
    return None


def _suite_from_task_id(task_id: str) -> str | None:
    if task_id.startswith("instance_"):
        return "ccb_swebenchpro"
    if task_id.startswith("sgt-"):
        return "ccb_pytorch"
    if task_id.startswith("big-code-"):
        return "ccb_largerepo"
    if task_id.startswith("dibench-"):
        return "ccb_dibench"
    if task_id.startswith("cr-"):
        return "ccb_codereview"
    if task_id.endswith("-doc-001"):
        return "ccb_k8sdocs"
    if task_id.startswith("lfl-"):
        return "ccb_linuxflbench"
    if task_id.startswith("bug_localization_") or task_id.startswith("refactor_rename_") or task_id.startswith("cross_file_reasoning_"):
        return "ccb_crossrepo"
    if "_expert_" in task_id:
        return "ccb_locobench"
    if task_id.startswith("multifile_editing-") or task_id.startswith("file_span_fix-") or task_id.startswith("dependency_recognition-"):
        return "ccb_dependeval"
    if task_id.startswith("repoqa-"):
        return "ccb_repoqa"
    if task_id.startswith("sweperf-"):
        return "ccb_sweperf"
    if task_id.startswith("tac-") or task_id.startswith("simple_test_"):
        return "ccb_tac"
    # Enterprise / governance
    if any(task_id.startswith(p) for p in ["dep-", "degraded-", "multi-team-", "repo-scoped-", "sensitive-file-", "stale-dep-"]):
        return "ccb_enterprise"
    if any(task_id.startswith(p) for p in ["license-", "eol-", "sbom-"]):
        return "ccb_governance"
    if any(task_id.startswith(p) for p in ["invest-"]):
        return "ccb_investigation"
    return None


def compute_cost(metrics: dict) -> float | None:
    """Compute USD cost from token counts, or return stored cost_usd."""
    cost = metrics.get("cost_usd")
    if cost is not None and cost > 0:
        return cost

    inp = metrics.get("input_tokens") or 0
    out = metrics.get("output_tokens") or 0
    cache_w = metrics.get("cache_creation_tokens") or 0
    cache_r = metrics.get("cache_read_tokens") or 0

    if inp == 0 and out == 0 and cache_w == 0 and cache_r == 0:
        return None

    return (
        inp * PRICING["input_per_token"]
        + out * PRICING["output_per_token"]
        + cache_w * PRICING["cache_write_per_token"]
        + cache_r * PRICING["cache_read_per_token"]
    )


def total_tokens(metrics: dict) -> int:
    """Compute total tokens (input + output + cache)."""
    return (
        (metrics.get("input_tokens") or 0)
        + (metrics.get("output_tokens") or 0)
        + (metrics.get("cache_creation_tokens") or 0)
        + (metrics.get("cache_read_tokens") or 0)
    )


def collect_all_metrics() -> dict:
    """Walk runs/official/ and collect task_metrics.json + result.json data.

    Returns dict keyed by (config, task_id) -> metrics dict (latest by timestamp).
    """
    all_tasks = {}  # key: (config, task_id) -> metrics dict

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir() or run_dir.name in ("archive", "MANIFEST.json"):
            continue
        if should_skip(run_dir.name):
            continue

        suite_from_dir = _suite_from_run_dir(run_dir.name)

        for config_dir in sorted(run_dir.iterdir()):
            if not config_dir.is_dir():
                continue
            config_name = config_dir.name
            if not is_config_dir(config_name):
                continue

            for batch_dir in sorted(config_dir.iterdir()):
                if not batch_dir.is_dir():
                    continue
                if should_skip(batch_dir.name):
                    continue

                # Handle two layouts: batch_timestamp/task__hash/ and task__hash/ directly
                if _is_batch_timestamp(batch_dir.name):
                    task_dirs = [d for d in sorted(batch_dir.iterdir()) if d.is_dir() and not should_skip(d.name)]
                elif "__" in batch_dir.name:
                    task_dirs = [batch_dir]
                else:
                    continue

                for task_dir in task_dirs:
                    metrics_file = task_dir / "task_metrics.json"
                    if not metrics_file.is_file():
                        continue

                    try:
                        metrics = json.loads(metrics_file.read_text())
                    except (json.JSONDecodeError, OSError):
                        continue

                    if not metrics:
                        continue

                    task_id = metrics.get("task_id", "")
                    if not task_id:
                        continue

                    benchmark = metrics.get("benchmark", "")
                    if not benchmark or benchmark == "unknown":
                        benchmark = suite_from_dir or _suite_from_task_id(task_id) or "unknown"
                    metrics["benchmark"] = benchmark

                    # Skip archived suites
                    if benchmark in ARCHIVED_SUITES:
                        continue

                    # Validity check
                    out_tokens = metrics.get("output_tokens")
                    if out_tokens is not None and out_tokens == 0:
                        continue
                    agent_time = metrics.get("agent_execution_seconds")
                    if agent_time is not None and agent_time < MIN_AGENT_TIME_SEC:
                        continue

                    # Get started_at for dedup
                    result_file = task_dir / "result.json"
                    started_at = ""
                    if result_file.is_file():
                        try:
                            rdata = json.loads(result_file.read_text())
                            started_at = rdata.get("started_at", "")
                        except Exception:
                            pass

                    key = (config_name, task_id)

                    if key in all_tasks:
                        if started_at > all_tasks[key].get("_started_at", ""):
                            metrics["_started_at"] = started_at
                            metrics["_task_dir"] = str(task_dir)
                            all_tasks[key] = metrics
                    else:
                        metrics["_started_at"] = started_at
                        metrics["_task_dir"] = str(task_dir)
                        all_tasks[key] = metrics

    return all_tasks


def main():
    print("Scanning runs/official/ for task_metrics.json files...", file=sys.stderr)
    all_metrics = collect_all_metrics()
    print(f"  Found {len(all_metrics)} valid task-config records", file=sys.stderr)

    # Separate by config
    baseline_tasks = {}
    sg_full_tasks = {}

    for (config, task_id), metrics in all_metrics.items():
        if config == "baseline":
            baseline_tasks[task_id] = metrics
        elif config == "sourcegraph_full":
            sg_full_tasks[task_id] = metrics

    print(f"  Baseline tasks: {len(baseline_tasks)}", file=sys.stderr)
    print(f"  SG_full tasks:  {len(sg_full_tasks)}", file=sys.stderr)

    # Find SG_full tasks with MCP ratio >= 50%
    high_mcp_tasks = {}
    for task_id, metrics in sg_full_tasks.items():
        mcp_ratio = metrics.get("mcp_ratio", 0.0) or 0.0
        tool_total = metrics.get("tool_calls_total", 0) or 0
        tool_mcp = metrics.get("tool_calls_mcp", 0) or 0

        # Recalculate ratio if needed
        if tool_total > 0:
            actual_ratio = tool_mcp / tool_total
        else:
            actual_ratio = 0.0

        if actual_ratio >= 0.50:
            high_mcp_tasks[task_id] = metrics
            high_mcp_tasks[task_id]["_actual_mcp_ratio"] = actual_ratio

    print(f"  SG_full tasks with MCP ratio >= 50%: {len(high_mcp_tasks)}", file=sys.stderr)

    # Match with baseline counterparts
    paired = []
    for task_id, sg_metrics in high_mcp_tasks.items():
        if task_id not in baseline_tasks:
            continue
        bl_metrics = baseline_tasks[task_id]

        bl_cost = compute_cost(bl_metrics)
        sg_cost = compute_cost(sg_metrics)

        if bl_cost is None or sg_cost is None or bl_cost <= 0:
            continue

        cost_ratio = sg_cost / bl_cost

        suite = sg_metrics.get("benchmark", "unknown")
        mcp_ratio = sg_metrics["_actual_mcp_ratio"]

        bl_reward = bl_metrics.get("reward", 0.0)
        sg_reward = sg_metrics.get("reward", 0.0)

        bl_total_tok = total_tokens(bl_metrics)
        sg_total_tok = total_tokens(sg_metrics)
        tok_ratio = sg_total_tok / bl_total_tok if bl_total_tok > 0 else None

        bl_agent_time = bl_metrics.get("agent_execution_seconds")
        sg_agent_time = sg_metrics.get("agent_execution_seconds")
        time_ratio = sg_agent_time / bl_agent_time if bl_agent_time and sg_agent_time and bl_agent_time > 0 else None

        paired.append({
            "task_id": task_id,
            "suite": suite,
            "baseline_cost": bl_cost,
            "sg_full_cost": sg_cost,
            "cost_ratio": cost_ratio,
            "mcp_ratio": mcp_ratio,
            "baseline_reward": bl_reward if bl_reward is not None else 0.0,
            "sg_full_reward": sg_reward if sg_reward is not None else 0.0,
            "baseline_total_tokens": bl_total_tok,
            "sg_full_total_tokens": sg_total_tok,
            "token_ratio": tok_ratio,
            "baseline_agent_time": bl_agent_time,
            "sg_full_agent_time": sg_agent_time,
            "time_ratio": time_ratio,
            "tool_calls_total": sg_metrics.get("tool_calls_total", 0),
            "tool_calls_mcp": sg_metrics.get("tool_calls_mcp", 0),
            "tool_calls_by_name": sg_metrics.get("tool_calls_by_name", {}),
        })

    # Sort by suite, then task_id
    paired.sort(key=lambda x: (x["suite"], x["task_id"]))

    print(f"  Paired tasks (both BL + SG_full, MCP>=50%): {len(paired)}", file=sys.stderr)
    print("", file=sys.stderr)

    if not paired:
        print("No paired tasks found with MCP ratio >= 50%.")
        return

    # Print per-task table
    print("=" * 160)
    print("  COST ANALYSIS: SG_full tasks with MCP ratio >= 50% vs Baseline")
    print("=" * 160)
    print()

    header = (
        f"{'Task ID':55s} {'Suite':18s} "
        f"{'BL Cost':>9s} {'SG Cost':>9s} {'Cost Ratio':>10s} "
        f"{'MCP%':>6s} "
        f"{'BL Reward':>9s} {'SG Reward':>9s} "
        f"{'Time Ratio':>10s}"
    )
    print(header)
    print("-" * len(header))

    for p in paired:
        time_ratio_str = f"{p['time_ratio']:.2f}x" if p["time_ratio"] is not None else "N/A"
        print(
            f"{p['task_id'][:55]:55s} {p['suite']:18s} "
            f"${p['baseline_cost']:>8.2f} ${p['sg_full_cost']:>8.2f} {p['cost_ratio']:>9.2f}x "
            f"{p['mcp_ratio']*100:>5.0f}% "
            f"{p['baseline_reward']:>9.3f} {p['sg_full_reward']:>9.3f} "
            f"{time_ratio_str:>10s}"
        )

    print()

    # Per-suite summary
    suite_data = defaultdict(list)
    for p in paired:
        suite_data[p["suite"]].append(p)

    print("=" * 120)
    print("  PER-SUITE AVERAGES")
    print("=" * 120)
    print()

    suite_header = (
        f"{'Suite':20s} {'N':>4s} "
        f"{'Avg BL Cost':>12s} {'Avg SG Cost':>12s} {'Avg Cost Ratio':>14s} "
        f"{'Med Cost Ratio':>14s} {'Avg MCP%':>8s} "
        f"{'Avg BL Rew':>10s} {'Avg SG Rew':>10s} "
        f"{'Avg Time Ratio':>14s}"
    )
    print(suite_header)
    print("-" * len(suite_header))

    all_cost_ratios = []
    all_time_ratios = []
    all_bl_costs = []
    all_sg_costs = []

    for suite in sorted(suite_data.keys()):
        tasks = suite_data[suite]
        n = len(tasks)

        avg_bl_cost = statistics.mean(t["baseline_cost"] for t in tasks)
        avg_sg_cost = statistics.mean(t["sg_full_cost"] for t in tasks)
        cost_ratios = [t["cost_ratio"] for t in tasks]
        avg_cost_ratio = statistics.mean(cost_ratios)
        med_cost_ratio = statistics.median(cost_ratios)
        avg_mcp = statistics.mean(t["mcp_ratio"] for t in tasks)
        avg_bl_rew = statistics.mean(t["baseline_reward"] for t in tasks)
        avg_sg_rew = statistics.mean(t["sg_full_reward"] for t in tasks)

        time_ratios = [t["time_ratio"] for t in tasks if t["time_ratio"] is not None]
        avg_time_ratio = statistics.mean(time_ratios) if time_ratios else None
        time_str = f"{avg_time_ratio:.2f}x" if avg_time_ratio is not None else "N/A"

        all_cost_ratios.extend(cost_ratios)
        all_time_ratios.extend(time_ratios)
        all_bl_costs.extend(t["baseline_cost"] for t in tasks)
        all_sg_costs.extend(t["sg_full_cost"] for t in tasks)

        print(
            f"{suite:20s} {n:>4d} "
            f"${avg_bl_cost:>11.2f} ${avg_sg_cost:>11.2f} {avg_cost_ratio:>13.2f}x "
            f"{med_cost_ratio:>13.2f}x {avg_mcp*100:>7.0f}% "
            f"{avg_bl_rew:>10.3f} {avg_sg_rew:>10.3f} "
            f"{time_str:>14s}"
        )

    # Overall summary
    print("-" * len(suite_header))
    overall_avg_bl = statistics.mean(all_bl_costs)
    overall_avg_sg = statistics.mean(all_sg_costs)
    overall_avg_ratio = statistics.mean(all_cost_ratios)
    overall_med_ratio = statistics.median(all_cost_ratios)
    overall_avg_mcp = statistics.mean(t["mcp_ratio"] for t in paired)
    overall_avg_bl_rew = statistics.mean(t["baseline_reward"] for t in paired)
    overall_avg_sg_rew = statistics.mean(t["sg_full_reward"] for t in paired)
    overall_avg_time = statistics.mean(all_time_ratios) if all_time_ratios else None
    overall_time_str = f"{overall_avg_time:.2f}x" if overall_avg_time is not None else "N/A"

    print(
        f"{'OVERALL':20s} {len(paired):>4d} "
        f"${overall_avg_bl:>11.2f} ${overall_avg_sg:>11.2f} {overall_avg_ratio:>13.2f}x "
        f"{overall_med_ratio:>13.2f}x {overall_avg_mcp*100:>7.0f}% "
        f"{overall_avg_bl_rew:>10.3f} {overall_avg_sg_rew:>10.3f} "
        f"{overall_time_str:>14s}"
    )

    print()

    # Additional breakdown: cost ratio distribution
    print("=" * 80)
    print("  COST RATIO DISTRIBUTION")
    print("=" * 80)
    print()

    cheaper = [r for r in all_cost_ratios if r < 0.9]
    similar = [r for r in all_cost_ratios if 0.9 <= r <= 1.1]
    more_expensive = [r for r in all_cost_ratios if r > 1.1]
    much_more = [r for r in all_cost_ratios if r > 2.0]

    print(f"  Cheaper (ratio < 0.9):          {len(cheaper):>3d} tasks ({len(cheaper)/len(all_cost_ratios)*100:.0f}%)")
    print(f"  Similar (0.9 - 1.1):            {len(similar):>3d} tasks ({len(similar)/len(all_cost_ratios)*100:.0f}%)")
    print(f"  More expensive (ratio > 1.1):   {len(more_expensive):>3d} tasks ({len(more_expensive)/len(all_cost_ratios)*100:.0f}%)")
    print(f"  Much more expensive (ratio > 2): {len(much_more):>3d} tasks ({len(much_more)/len(all_cost_ratios)*100:.0f}%)")
    print()

    # Quantiles
    sorted_ratios = sorted(all_cost_ratios)
    n = len(sorted_ratios)
    print(f"  Min:    {sorted_ratios[0]:.2f}x")
    print(f"  P10:    {sorted_ratios[int(n*0.10)]:.2f}x")
    print(f"  P25:    {sorted_ratios[int(n*0.25)]:.2f}x")
    print(f"  Median: {sorted_ratios[int(n*0.50)]:.2f}x")
    print(f"  P75:    {sorted_ratios[int(n*0.75)]:.2f}x")
    print(f"  P90:    {sorted_ratios[int(n*0.90)]:.2f}x")
    print(f"  Max:    {sorted_ratios[-1]:.2f}x")
    print()

    # Total cost comparison
    total_bl = sum(t["baseline_cost"] for t in paired)
    total_sg = sum(t["sg_full_cost"] for t in paired)
    print(f"  Total baseline cost:  ${total_bl:.2f}")
    print(f"  Total SG_full cost:   ${total_sg:.2f}")
    print(f"  Total cost ratio:     {total_sg/total_bl:.2f}x")
    print()

    # Top 5 most expensive (by ratio)
    print("=" * 80)
    print("  TOP 10 MOST EXPENSIVE (by cost ratio)")
    print("=" * 80)
    print()
    top_expensive = sorted(paired, key=lambda x: x["cost_ratio"], reverse=True)[:10]
    for p in top_expensive:
        print(f"  {p['cost_ratio']:>5.2f}x  ${p['baseline_cost']:.2f}->${p['sg_full_cost']:.2f}  "
              f"MCP={p['mcp_ratio']*100:.0f}%  "
              f"BL_rew={p['baseline_reward']:.2f} SG_rew={p['sg_full_reward']:.2f}  "
              f"{p['suite']:18s}  {p['task_id'][:50]}")

    print()

    # Top 5 cheapest (by ratio) -- where MCP saves money
    print("=" * 80)
    print("  TOP 10 CHEAPEST (MCP saves money)")
    print("=" * 80)
    print()
    top_cheapest = sorted(paired, key=lambda x: x["cost_ratio"])[:10]
    for p in top_cheapest:
        print(f"  {p['cost_ratio']:>5.2f}x  ${p['baseline_cost']:.2f}->${p['sg_full_cost']:.2f}  "
              f"MCP={p['mcp_ratio']*100:.0f}%  "
              f"BL_rew={p['baseline_reward']:.2f} SG_rew={p['sg_full_reward']:.2f}  "
              f"{p['suite']:18s}  {p['task_id'][:50]}")

    print()

    # MCP tool breakdown for high-MCP tasks
    print("=" * 80)
    print("  MCP TOOL BREAKDOWN (aggregate across all high-MCP tasks)")
    print("=" * 80)
    print()

    tool_totals = defaultdict(int)
    for p in paired:
        for tool, count in p.get("tool_calls_by_name", {}).items():
            tool_totals[tool] += count

    mcp_tools_total = 0
    local_tools_total = 0
    for tool, count in sorted(tool_totals.items(), key=lambda x: -x[1]):
        is_mcp = "mcp__sourcegraph" in tool
        if is_mcp:
            mcp_tools_total += count
        else:
            local_tools_total += count
        marker = "[MCP]" if is_mcp else "[local]"
        print(f"  {marker:8s} {tool:50s} {count:>6d}")

    print()
    print(f"  Total MCP calls:   {mcp_tools_total}")
    print(f"  Total local calls: {local_tools_total}")
    print(f"  MCP share:         {mcp_tools_total/(mcp_tools_total+local_tools_total)*100:.1f}%")


if __name__ == "__main__":
    main()
