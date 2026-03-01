#!/usr/bin/env python3
"""Design of Experiments: Variance decomposition and power-based task allocation.

Reads MANIFEST.json run_history to decompose total variance into:
  - Between-task-within-suite variance (sigma2_task): how heterogeneous tasks are within a suite
  - Within-task replicate variance (sigma2_rep): agent stochasticity across reruns
  - Between-suite variance (sigma2_suite): how different suites are from each other

Then computes per-suite required task counts for a given detectable effect size
and compares to the current uniform n=20 allocation.

Usage:
    python3 scripts/doe_variance_analysis.py
    python3 scripts/doe_variance_analysis.py --delta 0.10 --reps 3 --budget 180
    python3 scripts/doe_variance_analysis.py --json
    python3 scripts/doe_variance_analysis.py --include-mcp-unique
"""

import json
import math
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "runs" / "official" / "MANIFEST.json"
STAGING_DIR = PROJECT_ROOT / "runs" / "staging"

SDLC_SUITES = [
    "ccb_feature", "ccb_refactor", "ccb_debug", "ccb_design", "ccb_document",
    "ccb_fix", "ccb_secure", "ccb_test", "ccb_understand",
]

MCP_UNIQUE_SUITES = [
    "ccb_mcp_compliance", "ccb_mcp_crossorg", "ccb_mcp_crossrepo",
    "ccb_mcp_crossrepo_tracing", "ccb_mcp_domain", "ccb_mcp_incident",
    "ccb_mcp_migration", "ccb_mcp_onboarding", "ccb_mcp_org",
    "ccb_mcp_platform", "ccb_mcp_security",
]

BASELINE_CONFIGS = {"baseline", "baseline-local-direct", "baseline-local-artifact"}
MCP_CONFIGS = {"mcp", "mcp-remote-direct", "mcp-remote-artifact"}

# z-scores for standard power calculation
Z_ALPHA_HALF = 1.96   # two-sided alpha=0.05
Z_BETA = 0.842        # power=0.80
POWER_CONSTANT = (Z_ALPHA_HALF + Z_BETA) ** 2  # ~7.85


def load_run_history(manifest: dict) -> dict:
    """Extract per-task reward vectors from run_history, grouped by suite and config.

    Returns: {suite: {config_type: {task_name: [reward1, reward2, ...]}}}
    where config_type is 'baseline' or 'mcp'.
    """
    run_history = manifest.get("run_history", {})
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    for run_key, tasks in run_history.items():
        parts = run_key.split("/")
        if len(parts) != 2:
            continue
        suite, config = parts

        if config in BASELINE_CONFIGS:
            config_type = "baseline"
        elif config in MCP_CONFIGS:
            config_type = "mcp"
        else:
            continue

        for task_name, task_info in tasks.items():
            runs = task_info.get("runs", [])
            rewards = [
                r["reward"] for r in runs
                if r.get("reward") is not None and r.get("status") != "errored"
            ]
            if rewards:
                data[suite][config_type][task_name] = rewards

    return dict(data)


def load_staging_results(suites: list) -> dict:
    """Load task-level results from runs/staging/ for the given suites.

    Scans batch directories matching {suite}_haiku_YYYYMMDD_HHMMSS or
    {suite}_sonnet_YYYYMMDD_HHMMSS.  Parses nested result.json files,
    skipping batch-level summaries.

    Returns same shape as load_run_history:
      {suite: {config_type: {task_name: [reward1, reward2, ...]}}}
    """
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    if not STAGING_DIR.is_dir():
        return dict(data)

    suite_set = set(suites)
    for batch_dir in sorted(STAGING_DIR.iterdir()):
        if not batch_dir.is_dir():
            continue
        m = re.match(r'(ccb_\w+?)_(?:haiku|sonnet)_\d{8}_\d{6}', batch_dir.name)
        if not m:
            continue
        suite = m.group(1)
        if suite not in suite_set:
            continue

        for rj in batch_dir.rglob('result.json'):
            try:
                rdata = json.loads(rj.read_text())
            except Exception:
                continue
            if 'stats' in rdata:
                continue  # batch-level summary
            task_name = rdata.get('task_name', '')
            if not task_name:
                continue

            rel = str(rj.relative_to(batch_dir))
            if rel.startswith('baseline'):
                config_type = 'baseline'
            elif rel.startswith('mcp'):
                config_type = 'mcp'
            else:
                continue

            # Normalize task name: strip prefixes and Harbor random suffix
            tn = task_name
            for pfx in ('sgonly_', 'mcp_', 'bl_'):
                if tn.startswith(pfx):
                    tn = tn[len(pfx):]
            tn = re.sub(r'_[a-z0-9]{4,8}$', '', tn)

            vr = rdata.get('verifier_result')
            if vr is None:
                continue
            rewards_dict = vr.get('rewards')
            if rewards_dict is None:
                continue
            reward = rewards_dict.get('reward')
            if reward is not None:
                data[suite][config_type][tn].append(reward)

    return dict(data)


def merge_run_data(*datasets) -> dict:
    """Merge multiple run-data dicts (same shape as load_run_history output).

    Concatenates reward lists per (suite, config, task).
    """
    merged = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for ds in datasets:
        for suite, configs in ds.items():
            for ct, tasks in configs.items():
                for task, rewards in tasks.items():
                    merged[suite][ct][task].extend(rewards)
    return dict(merged)


def variance_decomposition_per_suite(
    suite_data: dict, min_reps: int = 2
) -> dict:
    """Decompose variance within a single suite's config arm.

    Uses one-way random effects ANOVA (tasks as groups, replicates as obs).
    Only includes tasks with >= min_reps valid runs.

    Returns dict with:
      - sigma2_task: between-task variance component
      - sigma2_rep: within-task (replicate) variance component
      - icc: intraclass correlation (proportion of variance due to tasks)
      - n_tasks: number of tasks included
      - n_obs: total observations
      - mean_reps: average replicates per task
      - grand_mean: overall mean reward
      - task_means: {task: mean} for all included tasks
      - task_stds: {task: std} for all included tasks
    """
    # Filter to tasks with sufficient replicates
    valid_tasks = {t: r for t, r in suite_data.items() if len(r) >= min_reps}
    if not valid_tasks:
        return None

    n_tasks = len(valid_tasks)
    all_obs = []
    task_means = {}
    task_stds = {}
    group_sizes = []

    for task_name, rewards in valid_tasks.items():
        task_means[task_name] = statistics.mean(rewards)
        task_stds[task_name] = statistics.stdev(rewards) if len(rewards) > 1 else 0.0
        group_sizes.append(len(rewards))
        all_obs.extend(rewards)

    n_obs = len(all_obs)
    grand_mean = statistics.mean(all_obs)
    mean_reps = n_obs / n_tasks

    # One-way ANOVA decomposition
    # SS_between = sum over tasks of n_i * (mean_i - grand_mean)^2
    ss_between = sum(
        len(valid_tasks[t]) * (task_means[t] - grand_mean) ** 2
        for t in valid_tasks
    )
    # SS_within = sum over tasks of sum over reps of (x_ij - mean_i)^2
    ss_within = sum(
        sum((x - task_means[t]) ** 2 for x in rewards)
        for t, rewards in valid_tasks.items()
    )

    df_between = n_tasks - 1
    df_within = n_obs - n_tasks

    ms_between = ss_between / df_between if df_between > 0 else 0
    ms_within = ss_within / df_within if df_within > 0 else 0

    # For unbalanced designs, use harmonic mean of group sizes for n_0
    if len(set(group_sizes)) == 1:
        n_0 = group_sizes[0]
    else:
        n_0 = (n_obs - sum(ni**2 for ni in group_sizes) / n_obs) / (n_tasks - 1)

    # Variance components (method of moments)
    sigma2_rep = ms_within
    sigma2_task = max(0, (ms_between - ms_within) / n_0)

    total_var = sigma2_task + sigma2_rep
    icc = sigma2_task / total_var if total_var > 0 else 0

    return {
        "sigma2_task": sigma2_task,
        "sigma2_rep": sigma2_rep,
        "total_var": total_var,
        "icc": icc,
        "n_tasks": n_tasks,
        "n_obs": n_obs,
        "mean_reps": round(mean_reps, 1),
        "grand_mean": round(grand_mean, 4),
        "ms_between": ms_between,
        "ms_within": ms_within,
        "task_means": task_means,
        "task_stds": task_stds,
    }


def required_tasks(sigma2_task: float, sigma2_rep: float, delta: float,
                   n_reps: int = 3) -> int:
    """Compute required number of tasks for 80% power at alpha=0.05 (two-sided).

    For detecting a treatment effect of size delta on the suite-level mean,
    accounting for both task heterogeneity and replicate noise.

    Formula: n >= 2 * (sigma2_task + sigma2_rep/n_reps) * (z_alpha/2 + z_beta)^2 / delta^2

    The factor of 2 accounts for estimating two group means (baseline vs MCP).
    """
    effective_var = sigma2_task + sigma2_rep / n_reps
    if delta <= 0 or effective_var <= 0:
        return 0
    n = 2 * effective_var * POWER_CONSTANT / (delta ** 2)
    return max(2, math.ceil(n))


def neyman_allocation(suite_variances: dict, total_budget: int) -> dict:
    """Compute Neyman-optimal allocation across suites.

    Allocates tasks proportional to within-suite SD to minimize
    the variance of the overall treatment effect estimate.

    Returns {suite: n_tasks}.
    """
    sds = {s: math.sqrt(v) for s, v in suite_variances.items() if v > 0}
    total_sd = sum(sds.values())
    if total_sd == 0:
        # Equal allocation fallback
        k = len(suite_variances)
        return {s: total_budget // k for s in suite_variances}

    allocation = {}
    remaining = total_budget
    for s in sorted(sds, key=lambda x: -sds[x]):
        n = max(2, round(total_budget * sds[s] / total_sd))
        allocation[s] = n
        remaining -= n

    # Distribute any remaining budget to highest-variance suites
    while remaining > 0:
        for s in sorted(sds, key=lambda x: -sds[x]):
            if remaining <= 0:
                break
            allocation[s] += 1
            remaining -= 1

    # If over budget, trim from lowest-variance suites
    while remaining < 0:
        for s in sorted(sds, key=lambda x: sds[x]):
            if remaining >= 0:
                break
            if allocation[s] > 2:
                allocation[s] -= 1
                remaining += 1

    return allocation


def minimax_power_allocation(decompositions: dict, delta: float,
                             n_reps: int = 3) -> dict:
    """Compute per-suite task counts so every suite has 80% power.

    Returns {suite: n_tasks}. Total budget is the sum (not fixed).
    """
    allocation = {}
    for suite, decomp in decompositions.items():
        if decomp is None:
            allocation[suite] = 20  # fallback
            continue
        allocation[suite] = required_tasks(
            decomp["sigma2_task"], decomp["sigma2_rep"], delta, n_reps
        )
    return allocation


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--delta", type=float, default=0.10,
                        help="Minimum detectable effect size (default: 0.10 = 10pp)")
    parser.add_argument("--reps", type=int, default=3,
                        help="Number of replicates per task (default: 3)")
    parser.add_argument("--budget", type=int, default=180,
                        help="Total task budget for Neyman allocation (default: 180)")
    parser.add_argument("--min-reps", type=int, default=2,
                        help="Min replicates to include a task (default: 2)")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON instead of formatted tables")
    parser.add_argument("--include-mcp-unique", action="store_true",
                        help="Include MCP-unique suites in analysis")
    parser.add_argument("--mcp-unique-only", action="store_true",
                        help="Analyze ONLY MCP-unique suites (excludes SDLC)")
    parser.add_argument("--include-staging", action="store_true",
                        help="Also load results from runs/staging/ (needed for MCP-unique)")
    parser.add_argument("--config", choices=["baseline", "mcp", "both"],
                        default="both",
                        help="Which config arm(s) to analyze (default: both)")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST_PATH.read_text())
    data = load_run_history(manifest)

    if args.mcp_unique_only:
        suites = list(MCP_UNIQUE_SUITES)
    else:
        suites = list(SDLC_SUITES)
        if args.include_mcp_unique:
            suites.extend(MCP_UNIQUE_SUITES)

    # Auto-enable staging loading when MCP-unique suites are requested
    if args.include_staging or args.include_mcp_unique or args.mcp_unique_only:
        staging_data = load_staging_results(suites)
        data = merge_run_data(data, staging_data)

    config_arms = []
    if args.config in ("baseline", "both"):
        config_arms.append("baseline")
    if args.config in ("mcp", "both"):
        config_arms.append("mcp")

    # --- Variance decomposition per suite per config ---
    decompositions = {}  # {(suite, config): decomp}
    for suite in suites:
        suite_data = data.get(suite, {})
        for config_type in config_arms:
            arm_data = suite_data.get(config_type, {})
            decomp = variance_decomposition_per_suite(arm_data, min_reps=args.min_reps)
            decompositions[(suite, config_type)] = decomp

    # --- Combined variance per suite (pool across configs) ---
    combined_decomps = {}
    for suite in suites:
        # Pool task-level data across both configs for power calculation
        # (treatment effect is estimated from both arms)
        all_task_data = {}
        suite_data = data.get(suite, {})
        for config_type in config_arms:
            arm_data = suite_data.get(config_type, {})
            for task, rewards in arm_data.items():
                key = f"{task}_{config_type}"
                all_task_data[key] = rewards

        decomp = variance_decomposition_per_suite(all_task_data, min_reps=args.min_reps)
        combined_decomps[suite] = decomp

    # --- Per-suite required n (minimax: every suite at 80% power) ---
    minimax = {}
    for suite in suites:
        decomp = combined_decomps.get(suite)
        if decomp:
            minimax[suite] = required_tasks(
                decomp["sigma2_task"], decomp["sigma2_rep"],
                args.delta, args.reps
            )
        else:
            minimax[suite] = 20

    # --- Neyman allocation for fixed budget ---
    effective_vars = {}
    for suite in suites:
        decomp = combined_decomps.get(suite)
        if decomp:
            effective_vars[suite] = decomp["sigma2_task"] + decomp["sigma2_rep"] / args.reps
        else:
            effective_vars[suite] = 0.05  # fallback
    neyman = neyman_allocation(effective_vars, args.budget)

    # --- Paired delta variance (baseline vs MCP) per suite ---
    delta_stats = {}
    for suite in suites:
        suite_data = data.get(suite, {})
        bl_data = suite_data.get("baseline", {})
        mcp_data = suite_data.get("mcp", {})
        paired_tasks = sorted(set(bl_data.keys()) & set(mcp_data.keys()))

        if not paired_tasks:
            delta_stats[suite] = None
            continue

        # Compute per-task deltas (mean across replicates)
        deltas = []
        for t in paired_tasks:
            bl_mean = statistics.mean(bl_data[t])
            mcp_mean = statistics.mean(mcp_data[t])
            deltas.append(mcp_mean - bl_mean)

        delta_stats[suite] = {
            "n_paired": len(paired_tasks),
            "mean_delta": statistics.mean(deltas),
            "std_delta": statistics.stdev(deltas) if len(deltas) > 1 else 0,
            "observed_effect": abs(statistics.mean(deltas)),
            "deltas": deltas,
        }

    # --- Power of current n=20 design ---
    current_power = {}
    for suite in suites:
        ds = delta_stats.get(suite)
        if ds and ds["std_delta"] > 0:
            # Observed power: can we detect the observed delta with n=20?
            # SE = std_delta / sqrt(n)
            n_current = 20
            se = ds["std_delta"] / math.sqrt(n_current)
            # For paired test: t = mean_delta / se
            if se > 0:
                t_stat = abs(ds["mean_delta"]) / se
                # Approximate power from t-statistic (normal approximation)
                # power ≈ Phi(t - z_alpha/2)
                # Use normal CDF approximation
                power_z = t_stat - Z_ALPHA_HALF
                # Phi approximation (good enough for reporting)
                power = _normal_cdf(power_z)
            else:
                power = 1.0
            current_power[suite] = round(power, 3)
        else:
            current_power[suite] = None

    # --- Output ---
    if args.json:
        _output_json(suites, config_arms, decompositions, combined_decomps,
                     minimax, neyman, delta_stats, current_power, args)
    else:
        _output_tables(suites, config_arms, decompositions, combined_decomps,
                       minimax, neyman, delta_stats, current_power, args)


def _normal_cdf(x: float) -> float:
    """Approximate standard normal CDF using error function approximation."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _output_json(suites, config_arms, decompositions, combined_decomps,
                 minimax, neyman, delta_stats, current_power, args):
    output = {
        "parameters": {
            "delta": args.delta,
            "n_reps": args.reps,
            "budget": args.budget,
            "min_reps": args.min_reps,
            "config_arms": config_arms,
        },
        "per_suite": {},
    }

    for suite in suites:
        short = suite.replace("ccb_mcp_", "mcp_").replace("ccb_", "")
        suite_out = {"suite": suite, "short_name": short}

        # Per-config decompositions
        for ct in config_arms:
            d = decompositions.get((suite, ct))
            if d:
                suite_out[f"{ct}_sigma2_task"] = round(d["sigma2_task"], 6)
                suite_out[f"{ct}_sigma2_rep"] = round(d["sigma2_rep"], 6)
                suite_out[f"{ct}_icc"] = round(d["icc"], 4)
                suite_out[f"{ct}_grand_mean"] = d["grand_mean"]
                suite_out[f"{ct}_n_tasks"] = d["n_tasks"]
                suite_out[f"{ct}_mean_reps"] = d["mean_reps"]

        # Combined decomposition
        cd = combined_decomps.get(suite)
        if cd:
            suite_out["combined_sigma2_task"] = round(cd["sigma2_task"], 6)
            suite_out["combined_sigma2_rep"] = round(cd["sigma2_rep"], 6)
            suite_out["combined_icc"] = round(cd["icc"], 4)

        # Allocations
        suite_out["current_n"] = 20
        suite_out["minimax_n"] = minimax.get(suite, 20)
        suite_out["neyman_n"] = neyman.get(suite, 20)

        # Delta stats
        ds = delta_stats.get(suite)
        if ds:
            suite_out["observed_delta"] = round(ds["mean_delta"], 4)
            suite_out["delta_std"] = round(ds["std_delta"], 4)
            suite_out["n_paired"] = ds["n_paired"]

        suite_out["current_power"] = current_power.get(suite)

        # Verdict
        mn = minimax.get(suite, 20)
        if mn > 25:
            suite_out["verdict"] = "UNDER-POWERED"
        elif mn < 15:
            suite_out["verdict"] = "OVER-SAMPLED"
        else:
            suite_out["verdict"] = "ADEQUATE"

        output["per_suite"][short] = suite_out

    # Totals
    output["minimax_total"] = sum(minimax.values())
    output["neyman_total"] = sum(neyman.values())
    output["current_total"] = 20 * len(suites)

    json.dump(output, sys.stdout, indent=2)
    print()


def _output_tables(suites, config_arms, decompositions, combined_decomps,
                   minimax, neyman, delta_stats, current_power, args):
    W = 130

    print(f"DOE Variance Analysis — Power-Based Task Allocation")
    print(f"  Detectable effect size (delta): {args.delta}")
    print(f"  Replicates per task: {args.reps}")
    print(f"  Neyman budget: {args.budget} tasks across {len(suites)} suites")
    print(f"  Config arms analyzed: {', '.join(config_arms)}")
    print("=" * W)

    # ---- Table 1: Variance Components per Config Arm ----
    for ct in config_arms:
        print(f"\n  VARIANCE COMPONENTS — {ct.upper()}")
        print("-" * W)
        print(f"  {'Suite':<18} {'n_task':>6} {'n_obs':>6} {'avg_rep':>7} "
              f"{'mean':>6} {'s2_task':>9} {'s2_rep':>9} {'s2_total':>9} "
              f"{'ICC':>6} {'sqrt(s2_task)':>13}")
        print("-" * W)

        for suite in suites:
            d = decompositions.get((suite, ct))
            short = suite.replace("ccb_mcp_", "mcp_").replace("ccb_", "")
            if d is None:
                print(f"  {short:<18} {'—':>6} {'—':>6} {'—':>7} "
                      f"{'—':>6} {'—':>9} {'—':>9} {'—':>9} {'—':>6} {'—':>13}")
                continue

            print(f"  {short:<18} {d['n_tasks']:>6} {d['n_obs']:>6} {d['mean_reps']:>7.1f} "
                  f"{d['grand_mean']:>6.3f} {d['sigma2_task']:>9.4f} {d['sigma2_rep']:>9.4f} "
                  f"{d['total_var']:>9.4f} {d['icc']:>6.3f} {math.sqrt(d['sigma2_task']):>13.4f}")

    # ---- Table 2: Power Analysis & Allocation ----
    print(f"\n\n  POWER ANALYSIS & TASK ALLOCATION (delta={args.delta}, reps={args.reps})")
    print("=" * W)
    print(f"  {'Suite':<18} {'s2_task':>9} {'s2_rep':>9} {'eff_var':>9} "
          f"{'curr_n':>6} {'need_n':>6} {'neyman_n':>8} "
          f"{'obs_delta':>10} {'delta_std':>10} {'power@20':>9} {'Verdict':<15}")
    print("-" * W)

    total_minimax = 0
    total_neyman = 0
    for suite in suites:
        short = suite.replace("ccb_mcp_", "mcp_").replace("ccb_", "")
        cd = combined_decomps.get(suite)
        mn = minimax.get(suite, 20)
        ny = neyman.get(suite, 20)
        ds = delta_stats.get(suite)
        pw = current_power.get(suite)
        total_minimax += mn
        total_neyman += ny

        if cd is None:
            print(f"  {short:<18} {'—':>9} {'—':>9} {'—':>9} "
                  f"{'20':>6} {'—':>6} {'—':>8} "
                  f"{'—':>10} {'—':>10} {'—':>9} {'NO DATA':<15}")
            continue

        eff_var = cd["sigma2_task"] + cd["sigma2_rep"] / args.reps

        if mn > 25:
            verdict = "UNDER-POWERED"
        elif mn < 15:
            verdict = "OVER-SAMPLED"
        else:
            verdict = "ADEQUATE"

        obs_d = f"{ds['mean_delta']:>+10.4f}" if ds else f"{'—':>10}"
        std_d = f"{ds['std_delta']:>10.4f}" if ds else f"{'—':>10}"
        pw_str = f"{pw:>9.3f}" if pw is not None else f"{'—':>9}"

        print(f"  {short:<18} {cd['sigma2_task']:>9.4f} {cd['sigma2_rep']:>9.4f} {eff_var:>9.4f} "
              f"{'20':>6} {mn:>6} {ny:>8} "
              f"{obs_d} {std_d} {pw_str} {verdict:<15}")

    print("-" * W)
    print(f"  {'TOTAL':<18} {'':>9} {'':>9} {'':>9} "
          f"{20*len(suites):>6} {total_minimax:>6} {total_neyman:>8}")

    # ---- Table 3: High-variance tasks (top 10 per suite) ----
    print(f"\n\n  TOP HIGH-VARIANCE TASKS (within-task replicate std, sorted desc)")
    print("=" * W)

    all_task_vars = []
    for suite in suites:
        for ct in config_arms:
            d = decompositions.get((suite, ct))
            if d is None:
                continue
            for task, std in d["task_stds"].items():
                if std > 0.05:  # filter noise
                    all_task_vars.append({
                        "suite": suite.replace("ccb_mcp_", "mcp_").replace("ccb_", ""),
                        "config": ct,
                        "task": task,
                        "mean": d["task_means"][task],
                        "std": std,
                    })

    all_task_vars.sort(key=lambda x: -x["std"])
    print(f"  {'Suite':<15} {'Config':<10} {'Task':<45} {'Mean':>6} {'Std':>6}")
    print("-" * W)
    for tv in all_task_vars[:30]:
        print(f"  {tv['suite']:<15} {tv['config']:<10} {tv['task']:<45} "
              f"{tv['mean']:>6.3f} {tv['std']:>6.3f}")

    # ---- Table 4: Paired delta distribution per suite ----
    print(f"\n\n  PAIRED DELTA DISTRIBUTION (MCP - Baseline, per-task mean across reps)")
    print("=" * W)
    print(f"  {'Suite':<18} {'n_pair':>6} {'mean_d':>8} {'std_d':>8} "
          f"{'min_d':>8} {'max_d':>8} {'frac>0':>7} {'frac<0':>7}")
    print("-" * W)

    for suite in suites:
        short = suite.replace("ccb_mcp_", "mcp_").replace("ccb_", "")
        ds = delta_stats.get(suite)
        if ds is None or not ds["deltas"]:
            print(f"  {short:<18} {'—':>6}")
            continue

        deltas = ds["deltas"]
        n = len(deltas)
        frac_pos = sum(1 for d in deltas if d > 0.001) / n
        frac_neg = sum(1 for d in deltas if d < -0.001) / n

        std_d = statistics.stdev(deltas) if n > 1 else 0.0
        print(f"  {short:<18} {n:>6} {statistics.mean(deltas):>+8.4f} "
              f"{std_d:>8.4f} {min(deltas):>+8.4f} "
              f"{max(deltas):>+8.4f} {frac_pos:>7.2f} {frac_neg:>7.2f}")

    # ---- Interpretation ----
    print(f"\n\n  INTERPRETATION")
    print("=" * W)
    print(f"""
  VARIANCE COMPONENTS:
    sigma2_task = between-task variance within a suite. High values mean tasks
      are heterogeneous (mix of easy and hard). Need more tasks to get stable
      suite-level estimates.
    sigma2_rep = within-task replicate variance. High values mean the agent is
      stochastic. More replicates help more than more tasks here.
    ICC = sigma2_task / (sigma2_task + sigma2_rep). High ICC means task selection
      dominates; low ICC means agent noise dominates.

  ALLOCATION:
    need_n = per-suite tasks required for 80% power to detect delta={args.delta}
    neyman_n = Neyman-optimal allocation of {args.budget} total tasks
      (proportional to within-suite SD)

  VERDICTS:
    UNDER-POWERED: need_n > 25 — current n=20 insufficient for this suite
    ADEQUATE: 15 <= need_n <= 25 — n=20 is reasonable
    OVER-SAMPLED: need_n < 15 — could reduce and reallocate to under-powered suites

  POWER@20: Estimated power of the current n=20 design to detect the OBSERVED
    effect size. Values < 0.80 suggest the current design can't reliably detect
    the actual baseline-vs-MCP difference for that suite.
""")


if __name__ == "__main__":
    main()
