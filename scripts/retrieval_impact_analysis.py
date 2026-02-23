#!/usr/bin/env python3
"""Downstream impact analysis: correlation and matched comparisons.

Analyzes the relationship between retrieval metrics and task outcomes (reward,
cost, time) using two complementary approaches:

1. **Correlation analysis** (US-008): Spearman rank correlation between
   retrieval metrics and outcome/cost variables. Reports association only,
   not causal claims.

2. **Matched comparison** (US-009): Paired-config comparisons on matched
   task sets (same task, baseline vs MCP config). Reports deltas with
   sample sizes and dispersion.

Usage:
    python3 scripts/retrieval_impact_analysis.py --run-dir runs/staging --all
    python3 scripts/retrieval_impact_analysis.py --events-dir runs/staging/fix_haiku_20260223/retrieval_events
    python3 scripts/retrieval_impact_analysis.py --run-dir runs/staging --all --output impact_analysis.json
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Repository root
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from ccb_metrics.ir_metrics import _normalize

# ---------------------------------------------------------------------------
# Spearman rank correlation (stdlib only)
# ---------------------------------------------------------------------------

def _rank(vals: list[float]) -> list[float]:
    n = len(vals)
    indexed = sorted(enumerate(vals), key=lambda t: t[1])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and indexed[j + 1][1] == indexed[j][1]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k][0]] = avg_rank
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> tuple[float, float]:
    """Spearman rank correlation. Returns (r, p_approx).

    Uses rank-based formula and normal approximation for p-value.
    Sample sizes and association-only language should accompany results.
    """
    n = len(x)
    if n < 3:
        return (0.0, 1.0)
    rx, ry = _rank(x), _rank(y)
    d_sq = sum((a - b) ** 2 for a, b in zip(rx, ry))
    r = 1.0 - (6.0 * d_sq) / (n * (n * n - 1))
    r = max(-1.0, min(1.0, r))
    if abs(r) >= 1.0:
        return (round(r, 6), 0.0)
    t_stat = r * math.sqrt((n - 2) / (1 - r * r))
    p = 2.0 * (1.0 - 0.5 * (1.0 + math.erf(abs(t_stat) / math.sqrt(2.0))))
    return (round(r, 6), round(p, 6))


def _interpret_correlation(r: float, p: float, n: int, x_name: str, y_name: str) -> str:
    """Generate association-only interpretation text."""
    abs_r = abs(r)
    strength = "strong" if abs_r >= 0.7 else "moderate" if abs_r >= 0.4 else "weak" if abs_r >= 0.2 else "negligible"
    sig = "statistically significant (p<0.05)" if p < 0.05 else "not statistically significant"
    direction = "positive" if r > 0 else "negative"
    return (
        f"{strength.title()} {direction} association (r={r:.3f}, p={p:.4f}, n={n}) "
        f"between {x_name} and {y_name}, {sig}. "
        f"This is an association, not a causal claim."
    )


# ---------------------------------------------------------------------------
# Load run outcome data (result.json / task_metrics.json)
# ---------------------------------------------------------------------------

def _load_task_outcomes(runs_root: Path, single_run: bool = False) -> dict[tuple[str, str], dict]:
    """Load outcome data (reward, cost, time) for all tasks.

    Returns dict keyed by (config_name, task_name) -> {reward, cost_usd, wall_clock_seconds, ...}
    """
    outcomes: dict[tuple[str, str], dict] = {}

    dirs_to_walk = [runs_root] if single_run else [
        d for d in sorted(runs_root.iterdir()) if d.is_dir() and d.name not in ("archive", "MANIFEST.json")
    ]

    import re
    _BATCH_RE = re.compile(r"\d{4}-\d{2}-\d{2}__\d{2}-\d{2}-\d{2}$")
    _SKIP = ("archive", "__broken", "__duplicate", "__all_errored", "__partial")

    for run_dir in dirs_to_walk:
        if any(p in run_dir.name for p in _SKIP):
            continue
        for config_dir in sorted(run_dir.iterdir()):
            if not config_dir.is_dir():
                continue
            config_name = config_dir.name
            if not any(config_name.startswith(p) for p in ("baseline", "mcp-", "sourcegraph")):
                continue
            for batch_dir in sorted(config_dir.iterdir()):
                if not batch_dir.is_dir() or not _BATCH_RE.match(batch_dir.name):
                    continue
                for task_dir in sorted(batch_dir.iterdir()):
                    if not task_dir.is_dir() or "__" not in task_dir.name:
                        continue
                    result_file = task_dir / "result.json"
                    if not result_file.is_file():
                        continue
                    try:
                        rdata = json.loads(result_file.read_text())
                    except (json.JSONDecodeError, OSError):
                        continue

                    task_name = rdata.get("task_name", task_dir.name.rsplit("__", 1)[0])
                    reward = None
                    vr = rdata.get("verifier_result", {})
                    if isinstance(vr, dict):
                        rw = vr.get("rewards", {})
                        if isinstance(rw, dict):
                            reward = rw.get("reward")

                    # Timing
                    wall_clock = None
                    agent_exec = rdata.get("agent_execution", {})
                    if isinstance(agent_exec, dict):
                        started = agent_exec.get("started_at")
                        finished = agent_exec.get("finished_at")
                        if started and finished:
                            from datetime import datetime
                            try:
                                s = datetime.fromisoformat(started.replace("Z", "+00:00"))
                                f = datetime.fromisoformat(finished.replace("Z", "+00:00"))
                                wall_clock = (f - s).total_seconds()
                            except (ValueError, TypeError):
                                pass

                    # Cost from task_metrics
                    cost_usd = None
                    output_tokens = None
                    tm_path = task_dir / "task_metrics.json"
                    if tm_path.is_file():
                        try:
                            tm = json.loads(tm_path.read_text())
                            cost_usd = tm.get("cost_usd")
                            output_tokens = tm.get("output_tokens")
                        except (json.JSONDecodeError, OSError):
                            pass

                    # Also try cost from result.json
                    if cost_usd is None:
                        ar = rdata.get("agent_result", {})
                        if isinstance(ar, dict):
                            cost_usd = ar.get("cost_usd")

                    key = (config_name, task_name)
                    # Dedup: keep latest
                    existing = outcomes.get(key)
                    started_at = rdata.get("started_at", "")
                    if existing and existing.get("started_at", "") >= started_at:
                        continue

                    outcomes[key] = {
                        "task_name": task_name,
                        "config_name": config_name,
                        "reward": reward,
                        "cost_usd": cost_usd,
                        "wall_clock_seconds": wall_clock,
                        "output_tokens": output_tokens,
                        "started_at": started_at,
                    }

    return outcomes


# ---------------------------------------------------------------------------
# Load retrieval metric artifacts
# ---------------------------------------------------------------------------

def _load_retrieval_metrics(path: Path) -> dict[tuple[str, str], dict]:
    """Load retrieval metric artifacts keyed by (config_name, task_name)."""
    metrics: dict[tuple[str, str], dict] = {}
    for f in sorted(path.rglob("*.retrieval_metrics.json")):
        try:
            data = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        prov = data.get("provenance", {})
        config = prov.get("config_name", "unknown")
        task = prov.get("task_name", f.stem.replace(".retrieval_metrics", ""))
        fm = data.get("file_level_metrics", {})
        if fm.get("computable"):
            metrics[(config, task)] = {
                "file_recall": fm.get("file_recall", 0.0),
                "mrr": fm.get("mrr", 0.0),
                "map_score": fm.get("map_score", 0.0),
                "context_efficiency": fm.get("context_efficiency", 0.0),
                "n_retrieved": fm.get("n_retrieved", 0),
                "ttfr_seconds": fm.get("ttfr_seconds"),
                "ttfr_tokens": fm.get("ttfr_tokens"),
            }
    return metrics


# =========================================================================
# US-008: Correlation analysis
# =========================================================================

def compute_correlations(
    retrieval_metrics: dict[tuple[str, str], dict],
    outcomes: dict[tuple[str, str], dict],
) -> dict:
    """Compute Spearman correlations between retrieval metrics and outcomes.

    Pairs are formed by joining on (config_name, task_name). Results include
    sample sizes and clearly labeled association-only language.
    """
    # Join datasets
    joined: list[dict] = []
    for key, rm in retrieval_metrics.items():
        outcome = outcomes.get(key)
        if outcome is None:
            continue
        if outcome.get("reward") is None:
            continue
        joined.append({**rm, **outcome})

    if len(joined) < 5:
        return {
            "computable": False,
            "reason": f"insufficient_paired_data (n={len(joined)}, need >= 5)",
            "n_joined": len(joined),
        }

    # Correlation pairs to compute
    retrieval_vars = ["file_recall", "mrr", "map_score", "context_efficiency"]
    outcome_vars = [
        ("reward", "verifier_outcome"),
        ("cost_usd", "cost_usd"),
        ("wall_clock_seconds", "runtime_seconds"),
        ("output_tokens", "output_tokens"),
    ]

    correlations: list[dict] = []
    for rv in retrieval_vars:
        for ov_key, ov_label in outcome_vars:
            x_vals = [r[rv] for r in joined if r.get(ov_key) is not None]
            y_vals = [r[ov_key] for r in joined if r.get(ov_key) is not None]

            # Filter to matched pairs
            pairs = [(r[rv], r[ov_key]) for r in joined if r.get(ov_key) is not None]
            if len(pairs) < 5:
                continue
            x = [p[0] for p in pairs]
            y = [p[1] for p in pairs]

            r, p = spearman(x, y)
            correlations.append({
                "retrieval_metric": rv,
                "outcome_metric": ov_label,
                "spearman_r": r,
                "spearman_p": p,
                "n": len(pairs),
                "interpretation": _interpret_correlation(r, p, len(pairs), rv, ov_label),
            })

    return {
        "computable": True,
        "n_joined": len(joined),
        "correlations": correlations,
    }


# =========================================================================
# US-009: Matched comparison analysis
# =========================================================================

def compute_matched_comparisons(
    retrieval_metrics: dict[tuple[str, str], dict],
    outcomes: dict[tuple[str, str], dict],
) -> dict:
    """Compute matched-task comparisons across paired configs.

    Constructs matched task sets: tasks that appear in both baseline and MCP
    configs. Reports deltas with sample size and dispersion (IQR).

    Labels distinguish comparative evidence from causal claims.
    """
    # Identify baseline and MCP config names
    all_configs = {k[0] for k in retrieval_metrics.keys()} | {k[0] for k in outcomes.keys()}
    baseline_configs = [c for c in all_configs if c.startswith("baseline")]
    mcp_configs = [c for c in all_configs if c.startswith("mcp-") or c.startswith("sourcegraph")]

    if not baseline_configs or not mcp_configs:
        return {
            "computable": False,
            "reason": "need_both_baseline_and_mcp_configs",
            "configs_found": sorted(all_configs),
        }

    bl_config = baseline_configs[0]
    mcp_config = mcp_configs[0]

    # Find matched tasks (present in both configs with outcomes)
    bl_tasks = {k[1] for k in outcomes if k[0] == bl_config and outcomes[k].get("reward") is not None}
    mcp_tasks = {k[1] for k in outcomes if k[0] == mcp_config and outcomes[k].get("reward") is not None}
    matched_tasks = sorted(bl_tasks & mcp_tasks)

    if len(matched_tasks) < 3:
        return {
            "computable": False,
            "reason": f"insufficient_matched_tasks (n={len(matched_tasks)}, need >= 3)",
            "baseline_config": bl_config,
            "mcp_config": mcp_config,
            "n_baseline": len(bl_tasks),
            "n_mcp": len(mcp_tasks),
        }

    # Compute deltas for matched tasks
    per_task: list[dict] = []
    reward_deltas: list[float] = []
    cost_deltas: list[float] = []
    time_deltas: list[float] = []
    file_recall_deltas: list[float] = []
    mrr_deltas: list[float] = []

    for task in matched_tasks:
        bl_outcome = outcomes.get((bl_config, task), {})
        mcp_outcome = outcomes.get((mcp_config, task), {})
        bl_rm = retrieval_metrics.get((bl_config, task), {})
        mcp_rm = retrieval_metrics.get((mcp_config, task), {})

        bl_reward = bl_outcome.get("reward", 0.0)
        mcp_reward = mcp_outcome.get("reward", 0.0)
        reward_delta = mcp_reward - bl_reward if bl_reward is not None and mcp_reward is not None else None
        if reward_delta is not None:
            reward_deltas.append(reward_delta)

        bl_cost = bl_outcome.get("cost_usd")
        mcp_cost = mcp_outcome.get("cost_usd")
        cost_delta = mcp_cost - bl_cost if bl_cost is not None and mcp_cost is not None else None
        if cost_delta is not None:
            cost_deltas.append(cost_delta)

        bl_time = bl_outcome.get("wall_clock_seconds")
        mcp_time = mcp_outcome.get("wall_clock_seconds")
        time_delta = mcp_time - bl_time if bl_time is not None and mcp_time is not None else None
        if time_delta is not None:
            time_deltas.append(time_delta)

        bl_fr = bl_rm.get("file_recall", 0.0)
        mcp_fr = mcp_rm.get("file_recall", 0.0)
        fr_delta = mcp_fr - bl_fr
        file_recall_deltas.append(fr_delta)

        bl_mrr = bl_rm.get("mrr", 0.0)
        mcp_mrr = mcp_rm.get("mrr", 0.0)
        mrr_delta = mcp_mrr - bl_mrr
        mrr_deltas.append(mrr_delta)

        per_task.append({
            "task_name": task,
            "reward_baseline": bl_reward,
            "reward_mcp": mcp_reward,
            "reward_delta": round(reward_delta, 4) if reward_delta is not None else None,
            "file_recall_baseline": round(bl_fr, 4),
            "file_recall_mcp": round(mcp_fr, 4),
            "file_recall_delta": round(fr_delta, 4),
            "mrr_baseline": round(bl_mrr, 4),
            "mrr_mcp": round(mcp_mrr, 4),
            "mrr_delta": round(mrr_delta, 4),
        })

    # Aggregate deltas with dispersion
    def _delta_summary(deltas: list[float], label: str) -> dict:
        if not deltas:
            return {"metric": label, "n": 0, "computable": False}
        sorted_d = sorted(deltas)
        q1 = sorted_d[len(sorted_d) // 4]
        q3 = sorted_d[3 * len(sorted_d) // 4]
        return {
            "metric": label,
            "n": len(deltas),
            "mean_delta": round(statistics.mean(deltas), 4),
            "median_delta": round(statistics.median(deltas), 4),
            "std_delta": round(statistics.stdev(deltas), 4) if len(deltas) > 1 else 0.0,
            "iqr": round(q3 - q1, 4),
            "positive_fraction": round(sum(1 for d in deltas if d > 0) / len(deltas), 4),
            "negative_fraction": round(sum(1 for d in deltas if d < 0) / len(deltas), 4),
            "zero_fraction": round(sum(1 for d in deltas if d == 0) / len(deltas), 4),
            "interpretation": (
                f"Matched comparison (n={len(deltas)}): MCP config shows "
                f"{'improvement' if statistics.mean(deltas) > 0 else 'decline'} "
                f"in {label} (mean delta={statistics.mean(deltas):.4f}, "
                f"median={statistics.median(deltas):.4f}). "
                f"This is a comparative observation, not a causal claim."
            ),
        }

    return {
        "computable": True,
        "baseline_config": bl_config,
        "mcp_config": mcp_config,
        "n_matched_tasks": len(matched_tasks),
        "n_baseline_only": len(bl_tasks - mcp_tasks),
        "n_mcp_only": len(mcp_tasks - bl_tasks),
        "deltas": {
            "reward": _delta_summary(reward_deltas, "reward"),
            "cost_usd": _delta_summary(cost_deltas, "cost_usd"),
            "wall_clock_seconds": _delta_summary(time_deltas, "wall_clock_seconds"),
            "file_recall": _delta_summary(file_recall_deltas, "file_recall"),
            "mrr": _delta_summary(mrr_deltas, "mrr"),
        },
        "per_task": per_task,
    }


# =========================================================================
# CLI
# =========================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Downstream impact analysis: correlations and matched comparisons.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Analyses performed:\n"
            "  1. Spearman correlation: retrieval metrics vs outcome/cost/time\n"
            "  2. Matched comparison: paired baseline vs MCP deltas\n"
            "\n"
            "Requires:\n"
            "  - Retrieval metric artifacts (run retrieval_eval_pipeline.py first)\n"
            "  - Task result.json files in the run directory\n"
        ),
    )
    parser.add_argument(
        "--run-dir", type=Path, required=True,
        help="Run directory or parent (with --all).",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Walk all runs under --run-dir.",
    )
    parser.add_argument(
        "--events-dir", type=Path, default=None,
        help="Direct path to retrieval_events/ directory (overrides auto-discovery).",
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=None,
        help="Write JSON output to file (default: stdout).",
    )
    args = parser.parse_args()

    run_dir = args.run_dir.resolve()

    # Load retrieval metrics
    if args.events_dir:
        retrieval_metrics = _load_retrieval_metrics(args.events_dir)
    else:
        # Discover retrieval_events/ dirs
        retrieval_metrics: dict[tuple[str, str], dict] = {}
        if args.all:
            for rd in sorted(run_dir.iterdir()):
                if rd.is_dir():
                    evdir = rd / "retrieval_events"
                    if evdir.is_dir():
                        retrieval_metrics.update(_load_retrieval_metrics(evdir))
        else:
            evdir = run_dir / "retrieval_events"
            if evdir.is_dir():
                retrieval_metrics = _load_retrieval_metrics(evdir)

    # Load outcomes
    outcomes = _load_task_outcomes(run_dir, single_run=not args.all)

    print(f"Loaded {len(retrieval_metrics)} retrieval metrics, {len(outcomes)} task outcomes",
          file=sys.stderr)

    # Run analyses
    correlation_results = compute_correlations(retrieval_metrics, outcomes)
    matched_results = compute_matched_comparisons(retrieval_metrics, outcomes)

    output = {
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "correlation_analysis": correlation_results,
        "matched_comparison": matched_results,
    }

    json_str = json.dumps(output, indent=2) + "\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json_str)
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(json_str)

    # Summary
    if correlation_results.get("computable"):
        print(f"\nCorrelation analysis: {len(correlation_results.get('correlations', []))} pairs computed "
              f"(n={correlation_results['n_joined']} joined tasks)", file=sys.stderr)
    else:
        print(f"\nCorrelation analysis: not computable — {correlation_results.get('reason', '?')}",
              file=sys.stderr)

    if matched_results.get("computable"):
        print(f"Matched comparison: {matched_results['n_matched_tasks']} matched tasks "
              f"({matched_results['baseline_config']} vs {matched_results['mcp_config']})",
              file=sys.stderr)
    else:
        print(f"Matched comparison: not computable — {matched_results.get('reason', '?')}",
              file=sys.stderr)


if __name__ == "__main__":
    main()
