#!/usr/bin/env python3
"""Compute bootstrap confidence intervals for all white paper results.

Reads MANIFEST.json, pairs baseline/MCP tasks, computes 10K-resample
bootstrap CIs on paired deltas. Reports two delta methods:

  delta_latest: uses the timestamp-deduped single result per task (from runs)
  delta_mean:   uses the mean reward across all valid runs per task (from run_history)

When a task has only one run, both methods produce identical values.

Usage:
    python3 scripts/compute_bootstrap_cis.py
    python3 scripts/compute_bootstrap_cis.py --n-bootstrap 10000
    python3 scripts/compute_bootstrap_cis.py --json
"""

import json
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "runs" / "official" / "MANIFEST.json"

# SDLC suites (170 tasks across 8 suites)
SDLC_SUITES = [
    "csb_sdlc_feature", "csb_sdlc_refactor", "csb_sdlc_debug", "csb_sdlc_design", "csb_sdlc_document",
    "csb_sdlc_fix", "csb_sdlc_secure", "csb_sdlc_test", "csb_sdlc_understand",
]

# MCP-unique suites (81 tasks across 11 suites)
MCP_UNIQUE_SUITES = [
    "csb_org_compliance", "csb_org_crossorg", "csb_org_crossrepo",
    "csb_org_crossrepo_tracing", "csb_org_domain", "csb_org_incident",
    "csb_org_migration", "csb_org_onboarding", "csb_org_org",
    "csb_org_platform", "csb_org_security",
]

# Baseline config names (both legacy and new)
BASELINE_CONFIGS = {"baseline", "baseline-local-direct", "baseline-local-artifact"}
# MCP config names (both legacy and new)
MCP_CONFIGS = {"mcp", "mcp-remote-direct", "mcp-remote-artifact"}


def bootstrap_ci(values: list[float], n_bootstrap: int = 10000, ci: float = 0.95):
    """Percentile bootstrap CI for the mean. Seed=42 for reproducibility."""
    if not values:
        return (0.0, 0.0, 0.0)
    mean_val = sum(values) / len(values)
    if len(values) == 1:
        return (mean_val, mean_val, mean_val)

    rng = random.Random(42)
    resamples = []
    for _ in range(n_bootstrap):
        sample = rng.choices(values, k=len(values))
        resamples.append(sum(sample) / len(sample))
    resamples.sort()

    alpha = 1 - ci
    lo_idx = int(alpha / 2 * n_bootstrap)
    hi_idx = int((1 - alpha / 2) * n_bootstrap) - 1
    return (mean_val, resamples[lo_idx], resamples[hi_idx])


def collect_tasks_for_suite(manifest: dict, suite: str) -> tuple[dict, dict]:
    """Collect all baseline and MCP task rewards for a suite (latest deduped).

    Returns (baseline_tasks, mcp_tasks) where each is {task_name: reward}.
    Merges across old/new config names and direct/artifact modes.
    """
    baseline_tasks = {}
    mcp_tasks = {}

    for run_key, run_data in manifest["runs"].items():
        parts = run_key.split("/")
        if len(parts) != 2:
            continue
        run_suite, config = parts
        if run_suite != suite:
            continue

        tasks = run_data.get("tasks", {})
        for task_name, task_info in tasks.items():
            reward = task_info.get("reward", 0.0)
            # Skip errored tasks
            if task_info.get("status") == "errored":
                continue

            if config in BASELINE_CONFIGS:
                # Keep latest (in case of overlap between legacy and new names)
                if task_name not in baseline_tasks:
                    baseline_tasks[task_name] = reward
            elif config in MCP_CONFIGS:
                if task_name not in mcp_tasks:
                    mcp_tasks[task_name] = reward

    return baseline_tasks, mcp_tasks


def collect_mean_tasks_for_suite(manifest: dict, suite: str) -> tuple[dict, dict]:
    """Collect mean rewards across all valid runs per task from run_history.

    Returns (baseline_tasks, mcp_tasks) where each is {task_name: mean_reward}.
    For single-run tasks, mean_reward equals the single run's reward.
    """
    baseline_tasks = {}
    mcp_tasks = {}

    run_history = manifest.get("run_history", {})

    for run_key, tasks in run_history.items():
        parts = run_key.split("/")
        if len(parts) != 2:
            continue
        run_suite, config = parts
        if run_suite != suite:
            continue

        for task_name, task_info in tasks.items():
            mean_reward = task_info.get("mean_reward", 0.0)

            if config in BASELINE_CONFIGS:
                if task_name not in baseline_tasks:
                    baseline_tasks[task_name] = mean_reward
            elif config in MCP_CONFIGS:
                if task_name not in mcp_tasks:
                    mcp_tasks[task_name] = mean_reward

    return baseline_tasks, mcp_tasks


def compute_paired_delta_ci(
    baseline_tasks: dict, mcp_tasks: dict, n_bootstrap: int = 10000
) -> dict:
    """Compute bootstrap CI on paired deltas."""
    # Find paired tasks
    paired_names = sorted(set(baseline_tasks.keys()) & set(mcp_tasks.keys()))
    if not paired_names:
        return {"n": 0, "baseline_mean": 0, "mcp_mean": 0, "delta": 0,
                "ci_lower": 0, "ci_upper": 0, "mcp_wins": 0,
                "paired_tasks": []}

    bl_rewards = [baseline_tasks[t] for t in paired_names]
    mcp_rewards = [mcp_tasks[t] for t in paired_names]
    deltas = [mcp_rewards[i] - bl_rewards[i] for i in range(len(paired_names))]

    bl_mean = sum(bl_rewards) / len(bl_rewards)
    mcp_mean = sum(mcp_rewards) / len(mcp_rewards)
    delta_mean, ci_lo, ci_hi = bootstrap_ci(deltas, n_bootstrap=n_bootstrap)

    # Count MCP wins
    mcp_wins = sum(1 for d in deltas if d > 0)

    return {
        "n": len(paired_names),
        "baseline_mean": round(bl_mean, 3),
        "mcp_mean": round(mcp_mean, 3),
        "delta": round(delta_mean, 3),
        "ci_lower": round(ci_lo, 3),
        "ci_upper": round(ci_hi, 3),
        "mcp_wins": mcp_wins,
        "paired_tasks": paired_names,
    }


def _compute_aggregates(
    all_results: dict, suites: list[str], manifest: dict,
    collect_fn, n_boot: int
) -> tuple[list, list]:
    """Collect paired rewards across suites using the given collector."""
    bl_all = []
    mcp_all = []
    for suite in suites:
        bl, mcp = collect_fn(manifest, suite)
        paired = sorted(set(bl.keys()) & set(mcp.keys()))
        bl_all.extend(bl[t] for t in paired)
        mcp_all.extend(mcp[t] for t in paired)
    return bl_all, mcp_all


def _find_sign_disagreements(
    latest_results: dict, mean_results: dict, suites: list[str]
) -> list[dict]:
    """Find tasks where delta_latest and delta_mean disagree in sign."""
    disagreements = []
    for suite in suites:
        lr = latest_results.get(suite, {})
        mr = mean_results.get(suite, {})
        paired_latest = lr.get("paired_tasks", [])
        paired_mean = mr.get("paired_tasks", [])
        # Use intersection of paired tasks
        common = sorted(set(paired_latest) & set(paired_mean))
        if not common:
            continue
        # We need per-task deltas — recompute from the result dicts
        # (they share the same paired_tasks list when both methods have the same pairing)
    return disagreements


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n-bootstrap", type=int, default=10000,
                        help="Number of bootstrap resamples (default: 10000)")
    parser.add_argument("--json", action="store_true",
                        help="Output raw JSON instead of formatted tables")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST_PATH.read_text())
    n_boot = args.n_bootstrap

    # ---- Per-suite results for BOTH methods ----
    latest_results = {}
    mean_results = {}

    for suite in SDLC_SUITES + MCP_UNIQUE_SUITES:
        # delta_latest: deduped single result
        bl_l, mcp_l = collect_tasks_for_suite(manifest, suite)
        latest_results[suite] = compute_paired_delta_ci(bl_l, mcp_l, n_bootstrap=n_boot)

        # delta_mean: mean across all valid runs
        bl_m, mcp_m = collect_mean_tasks_for_suite(manifest, suite)
        mean_results[suite] = compute_paired_delta_ci(bl_m, mcp_m, n_bootstrap=n_boot)

    # ---- Aggregate CIs for both methods ----
    def _agg(collect_fn):
        sdlc_bl, sdlc_mcp = _compute_aggregates(
            {}, SDLC_SUITES, manifest, collect_fn, n_boot)
        mcp_u_bl, mcp_u_mcp = _compute_aggregates(
            {}, MCP_UNIQUE_SUITES, manifest, collect_fn, n_boot)
        overall_bl = sdlc_bl + mcp_u_bl
        overall_mcp = sdlc_mcp + mcp_u_mcp
        return sdlc_bl, sdlc_mcp, mcp_u_bl, mcp_u_mcp, overall_bl, overall_mcp

    l_sdlc_bl, l_sdlc_mcp, l_mcp_u_bl, l_mcp_u_mcp, l_all_bl, l_all_mcp = \
        _agg(collect_tasks_for_suite)
    m_sdlc_bl, m_sdlc_mcp, m_mcp_u_bl, m_mcp_u_mcp, m_all_bl, m_all_mcp = \
        _agg(collect_mean_tasks_for_suite)

    def _deltas_and_ci(bl, mcp):
        deltas = [mcp[i] - bl[i] for i in range(len(bl))]
        mean_d, lo, hi = bootstrap_ci(deltas, n_bootstrap=n_boot)
        bl_m = sum(bl) / len(bl) if bl else 0
        mcp_m = sum(mcp) / len(mcp) if mcp else 0
        return {
            "n": len(deltas),
            "baseline_mean": round(bl_m, 3),
            "mcp_mean": round(mcp_m, 3),
            "delta": round(mean_d, 3),
            "ci_lower": round(lo, 3),
            "ci_upper": round(hi, 3),
        }

    latest_agg = {
        "overall": _deltas_and_ci(l_all_bl, l_all_mcp),
        "sdlc_total": _deltas_and_ci(l_sdlc_bl, l_sdlc_mcp),
        "mcp_unique_total": _deltas_and_ci(l_mcp_u_bl, l_mcp_u_mcp),
    }
    mean_agg = {
        "overall": _deltas_and_ci(m_all_bl, m_all_mcp),
        "sdlc_total": _deltas_and_ci(m_sdlc_bl, m_sdlc_mcp),
        "mcp_unique_total": _deltas_and_ci(m_mcp_u_bl, m_mcp_u_mcp),
    }

    # ---- Find per-task sign disagreements ----
    sign_flips = []
    for suite in SDLC_SUITES + MCP_UNIQUE_SUITES:
        bl_l, mcp_l = collect_tasks_for_suite(manifest, suite)
        bl_m, mcp_m = collect_mean_tasks_for_suite(manifest, suite)
        paired = sorted(set(bl_l.keys()) & set(mcp_l.keys())
                        & set(bl_m.keys()) & set(mcp_m.keys()))
        for t in paired:
            d_latest = mcp_l[t] - bl_l[t]
            d_mean = mcp_m[t] - bl_m[t]
            # Sign disagreement: one positive, one negative (ignore ties at 0)
            if (d_latest > 0.001 and d_mean < -0.001) or \
               (d_latest < -0.001 and d_mean > 0.001):
                sign_flips.append({
                    "suite": suite,
                    "task": t,
                    "delta_latest": round(d_latest, 4),
                    "delta_mean": round(d_mean, 4),
                })

    # ---- Multi-run summary ----
    run_history = manifest.get("run_history", {})
    multi_run_tasks = 0
    for rh_key, tasks in run_history.items():
        for task_data in tasks.values():
            if task_data.get("n_runs", 1) > 1:
                multi_run_tasks += 1

    if args.json:
        output = {
            "n_bootstrap": n_boot,
            "delta_latest": {
                **latest_agg,
                "per_suite": {s: {k: v for k, v in r.items() if k != "paired_tasks"}
                              for s, r in latest_results.items()},
            },
            "delta_mean": {
                **mean_agg,
                "per_suite": {s: {k: v for k, v in r.items() if k != "paired_tasks"}
                              for s, r in mean_results.items()},
            },
            "sign_flips": sign_flips,
            "multi_run_tasks": multi_run_tasks,
        }
        json.dump(output, sys.stdout, indent=2)
        print()
        return

    # ---- Formatted output ----
    def _ci_str(lo, hi):
        return f"[{lo:+.3f}, {hi:+.3f}]"

    def _excludes_zero(lo, hi):
        return lo > 0 or hi < 0

    print(f"Bootstrap CIs ({n_boot:,} resamples, seed=42, percentile method)")
    print(f"Tasks with multiple valid runs: {multi_run_tasks}")
    print("=" * 120)

    # ============================================================
    # DELTA_LATEST (deduped single result)
    # ============================================================
    print(f"\n{'DELTA_LATEST (timestamp-deduped single result per task)':^120}")
    print("=" * 120)

    print(f"\n{'AGGREGATE':^120}")
    print("-" * 120)
    print(f"{'Slice':<25} {'n':>4} {'BL Mean':>8} {'MCP Mean':>9} {'Delta':>7} {'95% CI':>20}")
    print("-" * 120)

    for label, key in [("Overall", "overall"), ("SDLC total", "sdlc_total"),
                        ("MCP-unique total", "mcp_unique_total")]:
        r = latest_agg[key]
        sig = "*" if _excludes_zero(r["ci_lower"], r["ci_upper"]) and r["n"] > 1 else ""
        ci = _ci_str(r["ci_lower"], r["ci_upper"]) if r["n"] > 1 else "—"
        print(f"{label:<25} {r['n']:>4} {r['baseline_mean']:>8.3f} {r['mcp_mean']:>9.3f} {r['delta']:>+7.3f} {ci:>20} {sig}")

    print(f"\n{'SDLC SUITES':^120}")
    print("-" * 120)
    print(f"{'Suite':<25} {'n':>4} {'BL Mean':>8} {'MCP Mean':>9} {'Delta':>7} {'95% CI':>20}")
    print("-" * 120)
    for suite in SDLC_SUITES:
        r = latest_results[suite]
        short = suite.replace("csb_sdlc_", "").replace("ccb_", "")
        sig = "*" if _excludes_zero(r["ci_lower"], r["ci_upper"]) and r["n"] > 1 else ""
        ci = _ci_str(r["ci_lower"], r["ci_upper"]) if r["n"] > 1 else "—"
        print(f"{short:<25} {r['n']:>4} {r['baseline_mean']:>8.3f} {r['mcp_mean']:>9.3f} {r['delta']:>+7.3f} {ci:>20} {sig}")

    print(f"\n{'MCP-UNIQUE SUITES':^120}")
    print("-" * 120)
    print(f"{'Suite':<25} {'n':>4} {'BL Mean':>8} {'MCP Mean':>9} {'Delta':>7} {'95% CI':>20}")
    print("-" * 120)
    for suite in MCP_UNIQUE_SUITES:
        r = latest_results[suite]
        short = suite.replace("csb_org_", "").replace("ccb_mcp_", "")
        sig = "*" if _excludes_zero(r["ci_lower"], r["ci_upper"]) and r["n"] > 1 else ""
        ci = _ci_str(r["ci_lower"], r["ci_upper"]) if r["n"] > 1 else "—"
        print(f"{short:<25} {r['n']:>4} {r['baseline_mean']:>8.3f} {r['mcp_mean']:>9.3f} {r['delta']:>+7.3f} {ci:>20} {sig}")

    # ============================================================
    # DELTA_MEAN (mean reward across all valid runs)
    # ============================================================
    print(f"\n\n{'DELTA_MEAN (mean reward across all valid runs per task)':^120}")
    print("=" * 120)

    print(f"\n{'AGGREGATE':^120}")
    print("-" * 120)
    print(f"{'Slice':<25} {'n':>4} {'BL Mean':>8} {'MCP Mean':>9} {'Delta':>7} {'95% CI':>20}")
    print("-" * 120)

    for label, key in [("Overall", "overall"), ("SDLC total", "sdlc_total"),
                        ("MCP-unique total", "mcp_unique_total")]:
        r = mean_agg[key]
        sig = "*" if _excludes_zero(r["ci_lower"], r["ci_upper"]) and r["n"] > 1 else ""
        ci = _ci_str(r["ci_lower"], r["ci_upper"]) if r["n"] > 1 else "—"
        print(f"{label:<25} {r['n']:>4} {r['baseline_mean']:>8.3f} {r['mcp_mean']:>9.3f} {r['delta']:>+7.3f} {ci:>20} {sig}")

    print(f"\n{'SDLC SUITES':^120}")
    print("-" * 120)
    print(f"{'Suite':<25} {'n':>4} {'BL Mean':>8} {'MCP Mean':>9} {'Delta':>7} {'95% CI':>20}")
    print("-" * 120)
    for suite in SDLC_SUITES:
        r = mean_results[suite]
        short = suite.replace("csb_sdlc_", "").replace("ccb_", "")
        sig = "*" if _excludes_zero(r["ci_lower"], r["ci_upper"]) and r["n"] > 1 else ""
        ci = _ci_str(r["ci_lower"], r["ci_upper"]) if r["n"] > 1 else "—"
        print(f"{short:<25} {r['n']:>4} {r['baseline_mean']:>8.3f} {r['mcp_mean']:>9.3f} {r['delta']:>+7.3f} {ci:>20} {sig}")

    print(f"\n{'MCP-UNIQUE SUITES':^120}")
    print("-" * 120)
    print(f"{'Suite':<25} {'n':>4} {'BL Mean':>8} {'MCP Mean':>9} {'Delta':>7} {'95% CI':>20}")
    print("-" * 120)
    for suite in MCP_UNIQUE_SUITES:
        r = mean_results[suite]
        short = suite.replace("csb_org_", "").replace("ccb_mcp_", "")
        sig = "*" if _excludes_zero(r["ci_lower"], r["ci_upper"]) and r["n"] > 1 else ""
        ci = _ci_str(r["ci_lower"], r["ci_upper"]) if r["n"] > 1 else "—"
        print(f"{short:<25} {r['n']:>4} {r['baseline_mean']:>8.3f} {r['mcp_mean']:>9.3f} {r['delta']:>+7.3f} {ci:>20} {sig}")

    # ============================================================
    # COMPARISON
    # ============================================================
    print(f"\n\n{'COMPARISON: delta_latest vs delta_mean':^120}")
    print("=" * 120)
    print(f"{'Slice':<25} {'n':>4} {'D_latest':>9} {'CI_latest':>20}   {'D_mean':>9} {'CI_mean':>20}  {'Diff':>7}")
    print("-" * 120)

    for label, key in [("Overall", "overall"), ("SDLC total", "sdlc_total"),
                        ("MCP-unique total", "mcp_unique_total")]:
        rl = latest_agg[key]
        rm = mean_agg[key]
        diff = round(rl["delta"] - rm["delta"], 3)
        ci_l = _ci_str(rl["ci_lower"], rl["ci_upper"]) if rl["n"] > 1 else "—"
        ci_m = _ci_str(rm["ci_lower"], rm["ci_upper"]) if rm["n"] > 1 else "—"
        print(f"{label:<25} {rl['n']:>4} {rl['delta']:>+9.3f} {ci_l:>20}   {rm['delta']:>+9.3f} {ci_m:>20}  {diff:>+7.3f}")

    print()
    for suite_list, header in [(SDLC_SUITES, "SDLC"), (MCP_UNIQUE_SUITES, "MCP-UNIQUE")]:
        print(f"  {header}:")
        for suite in suite_list:
            rl = latest_results[suite]
            rm = mean_results[suite]
            short = suite.replace("csb_org_", "").replace("csb_org_", "").replace("csb_sdlc_", "").replace("ccb_mcp_", "").replace("ccb_", "")
            diff = round(rl["delta"] - rm["delta"], 3)
            if abs(diff) < 0.001:
                continue  # Skip identical rows
            print(f"    {short:<23} {rl['n']:>4} {rl['delta']:>+9.3f}   vs   {rm['delta']:>+9.3f}   diff={diff:>+.3f}")

    # ============================================================
    # SIGN FLIPS
    # ============================================================
    if sign_flips:
        print(f"\n\n{'SIGN DISAGREEMENTS (delta_latest vs delta_mean)':^120}")
        print("=" * 120)
        print(f"{'Suite':<30} {'Task':<40} {'D_latest':>10} {'D_mean':>10}")
        print("-" * 120)
        for sf in sorted(sign_flips, key=lambda x: -abs(x["delta_latest"] - x["delta_mean"])):
            short = sf["suite"].replace("csb_org_", "").replace("csb_sdlc_", "").replace("ccb_mcp_", "").replace("ccb_", "")
            print(f"{short:<30} {sf['task']:<40} {sf['delta_latest']:>+10.4f} {sf['delta_mean']:>+10.4f}")
        print(f"\nTotal sign disagreements: {len(sign_flips)}")

    print()
    print("* = 95% CI excludes zero")
    print()

    # Summary for white paper copy
    print("=" * 120)
    print("WHITE PAPER COPY (markdown tables)")
    print("=" * 120)

    lo_l = latest_agg["overall"]
    lo_m = mean_agg["overall"]
    ls_l = latest_agg["sdlc_total"]
    ls_m = mean_agg["sdlc_total"]
    lm_l = latest_agg["mcp_unique_total"]
    lm_m = mean_agg["mcp_unique_total"]

    print(f"\n**delta_latest** (deduped single result):")
    print(f"  Overall: delta **{lo_l['delta']:+.3f}** (95% CI: [{lo_l['ci_lower']:+.3f}, {lo_l['ci_upper']:+.3f}])")
    print(f"  SDLC: delta **{ls_l['delta']:+.3f}** (95% CI: [{ls_l['ci_lower']:+.3f}, {ls_l['ci_upper']:+.3f}])")
    print(f"  MCP-unique: delta **{lm_l['delta']:+.3f}** (95% CI: [{lm_l['ci_lower']:+.3f}, {lm_l['ci_upper']:+.3f}])")

    print(f"\n**delta_mean** (mean across all valid runs):")
    print(f"  Overall: delta **{lo_m['delta']:+.3f}** (95% CI: [{lo_m['ci_lower']:+.3f}, {lo_m['ci_upper']:+.3f}])")
    print(f"  SDLC: delta **{ls_m['delta']:+.3f}** (95% CI: [{ls_m['ci_lower']:+.3f}, {ls_m['ci_upper']:+.3f}])")
    print(f"  MCP-unique: delta **{lm_m['delta']:+.3f}** (95% CI: [{lm_m['ci_lower']:+.3f}, {lm_m['ci_upper']:+.3f}])")


if __name__ == "__main__":
    main()
