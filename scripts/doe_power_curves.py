#!/usr/bin/env python3
"""DOE Power Curves: Minimum task counts for detecting moderating effects.

Computes the minimum number of tasks needed to detect:
  1. Main effect of MCP (overall treatment effect)
  2. Config x SDLC phase interaction (does MCP help differently per phase?)
  3. Config x codebase size interaction (does MCP help more in larger codebases?)
  4. Config x complexity interaction (does MCP help more on harder tasks?)

Uses empirical variance estimates from existing pilot runs (MANIFEST.json).
Models the experiment as a mixed-effects regression:
  reward ~ config * sdlc_phase * log(codebase_size) * complexity + (1|task)

Reports power curves showing how power increases with task count for each effect.

Usage:
    python3 scripts/doe_power_curves.py
    python3 scripts/doe_power_curves.py --reps 5 --arms 3
    python3 scripts/doe_power_curves.py --json
"""

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = PROJECT_ROOT / "runs" / "official" / "MANIFEST.json"
SELECTION_PATH = PROJECT_ROOT / "configs" / "selected_benchmark_tasks.json"

SDLC_SUITES = [
    "csb_sdlc_feature", "csb_sdlc_refactor", "csb_sdlc_debug", "csb_sdlc_design", "csb_sdlc_document",
    "csb_sdlc_fix", "csb_sdlc_secure", "csb_sdlc_test", "csb_sdlc_understand",
]

BASELINE_CONFIGS = {"baseline", "baseline-local-direct", "baseline-local-artifact"}
MCP_CONFIGS = {"mcp", "mcp-remote-direct", "mcp-remote-artifact"}

Z_ALPHA_HALF = 1.96  # two-sided alpha=0.05


def normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def power_for_effect(effect_size: float, se: float, alpha: float = 0.05) -> float:
    """Power to detect a given effect size with a given standard error."""
    if se <= 0:
        return 1.0
    z_crit = 1.96 if alpha == 0.05 else 2.576
    noncentrality = abs(effect_size) / se
    return normal_cdf(noncentrality - z_crit)


def load_paired_data(manifest: dict) -> list[dict]:
    """Load all paired (baseline, MCP) task observations from run_history.

    Returns list of {suite, task, bl_rewards: [...], mcp_rewards: [...],
                     bl_mean, mcp_mean, delta, bl_var, mcp_var}
    """
    run_history = manifest.get("run_history", {})

    # Collect per-(suite, config_type, task) reward vectors
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for run_key, tasks in run_history.items():
        parts = run_key.split("/")
        if len(parts) != 2:
            continue
        suite, config = parts
        if suite not in SDLC_SUITES:
            continue

        if config in BASELINE_CONFIGS:
            ct = "baseline"
        elif config in MCP_CONFIGS:
            ct = "mcp"
        else:
            continue

        for task_name, task_info in tasks.items():
            runs = task_info.get("runs", [])
            for r in runs:
                if r.get("reward") is not None and r.get("status") != "errored":
                    data[suite][ct][task_name].append(r["reward"])

    # Build paired records
    paired = []
    for suite in SDLC_SUITES:
        bl_tasks = data.get(suite, {}).get("baseline", {})
        mcp_tasks = data.get(suite, {}).get("mcp", {})
        common = sorted(set(bl_tasks.keys()) & set(mcp_tasks.keys()))

        for task in common:
            bl = bl_tasks[task]
            mcp = mcp_tasks[task]
            if len(bl) < 2 or len(mcp) < 2:
                continue
            bl_mean = statistics.mean(bl)
            mcp_mean = statistics.mean(mcp)
            paired.append({
                "suite": suite,
                "task": task,
                "bl_rewards": bl,
                "mcp_rewards": mcp,
                "bl_mean": bl_mean,
                "mcp_mean": mcp_mean,
                "delta": mcp_mean - bl_mean,
                "bl_var": statistics.variance(bl),
                "mcp_var": statistics.variance(mcp),
                "n_bl": len(bl),
                "n_mcp": len(mcp),
            })

    return paired


def load_task_metadata(selection_path: Path) -> dict:
    """Load task-level covariates from selected_benchmark_tasks.json.

    Returns {task_name: {language, difficulty, context_length, files_count,
                         mcp_benefit_score, repo, ...}}
    """
    if not selection_path.exists():
        return {}
    raw = json.loads(selection_path.read_text())
    # Handle both flat list and nested {tasks: [...]} formats
    if isinstance(raw, dict):
        sel = raw.get("tasks", [])
    elif isinstance(raw, list):
        sel = raw
    else:
        return {}
    meta = {}
    for task in sel:
        if not isinstance(task, dict):
            continue
        name = task.get("task_id", task.get("task_name", task.get("name", "")))
        meta[name] = {
            "language": task.get("language", "unknown"),
            "difficulty": task.get("difficulty", "hard"),
            "context_length": task.get("context_length", 0),
            "files_count": task.get("files_count", 0),
            "mcp_benefit_score": task.get("mcp_benefit_score", 0),
            "repo": task.get("repo", ""),
            "benchmark": task.get("benchmark", ""),
        }
    return meta


def estimate_variance_components(paired: list[dict]) -> dict:
    """Estimate key variance components from paired pilot data.

    Returns:
      sigma2_total: total variance of reward scores
      sigma2_between_suite: between-suite variance
      sigma2_task_within_suite: between-task-within-suite variance
      sigma2_replicate: within-task replicate variance
      sigma2_delta: variance of paired deltas (MCP - baseline)
      sigma2_delta_within_suite: per-suite delta variance (pooled)
      per_suite_stats: {suite: {mean_delta, std_delta, n, sigma2_delta}}
    """
    # All individual rewards
    all_rewards = []
    for p in paired:
        all_rewards.extend(p["bl_rewards"])
        all_rewards.extend(p["mcp_rewards"])
    sigma2_total = statistics.variance(all_rewards)

    # Between-suite means
    suite_means = defaultdict(list)
    for p in paired:
        suite_means[p["suite"]].append(p["bl_mean"])
        suite_means[p["suite"]].append(p["mcp_mean"])
    suite_grand_means = {s: statistics.mean(v) for s, v in suite_means.items()}
    overall_mean = statistics.mean(all_rewards)

    n_suites = len(suite_grand_means)
    if n_suites > 1:
        sigma2_between_suite = statistics.variance(list(suite_grand_means.values()))
    else:
        sigma2_between_suite = 0

    # Within-task replicate variance (pool across all tasks)
    rep_vars = []
    rep_weights = []
    for p in paired:
        for rewards in [p["bl_rewards"], p["mcp_rewards"]]:
            if len(rewards) > 1:
                rep_vars.append(statistics.variance(rewards))
                rep_weights.append(len(rewards) - 1)
    if rep_weights:
        sigma2_replicate = sum(v * w for v, w in zip(rep_vars, rep_weights)) / sum(rep_weights)
    else:
        sigma2_replicate = 0

    # Between-task-within-suite variance
    task_means_all = [statistics.mean(p["bl_rewards"] + p["mcp_rewards"]) for p in paired]
    sigma2_task_total = statistics.variance(task_means_all) if len(task_means_all) > 1 else 0
    sigma2_task_within_suite = max(0, sigma2_task_total - sigma2_between_suite)

    # Delta (treatment effect) variance
    all_deltas = [p["delta"] for p in paired]
    sigma2_delta = statistics.variance(all_deltas) if len(all_deltas) > 1 else 0

    # Per-suite delta statistics
    suite_deltas = defaultdict(list)
    for p in paired:
        suite_deltas[p["suite"]].append(p["delta"])

    per_suite_stats = {}
    for suite, deltas in suite_deltas.items():
        per_suite_stats[suite] = {
            "mean_delta": statistics.mean(deltas),
            "std_delta": statistics.stdev(deltas) if len(deltas) > 1 else 0,
            "sigma2_delta": statistics.variance(deltas) if len(deltas) > 1 else 0,
            "n": len(deltas),
        }

    # Pooled within-suite delta variance
    pooled_delta_vars = []
    pooled_delta_weights = []
    for suite, stats in per_suite_stats.items():
        if stats["n"] > 1:
            pooled_delta_vars.append(stats["sigma2_delta"])
            pooled_delta_weights.append(stats["n"] - 1)
    sigma2_delta_within_suite = (
        sum(v * w for v, w in zip(pooled_delta_vars, pooled_delta_weights))
        / sum(pooled_delta_weights)
        if pooled_delta_weights else 0
    )

    return {
        "sigma2_total": sigma2_total,
        "sigma2_between_suite": sigma2_between_suite,
        "sigma2_task_within_suite": sigma2_task_within_suite,
        "sigma2_replicate": sigma2_replicate,
        "sigma2_delta": sigma2_delta,
        "sigma2_delta_within_suite": sigma2_delta_within_suite,
        "per_suite_stats": per_suite_stats,
        "overall_mean_delta": statistics.mean(all_deltas),
        "overall_std_delta": statistics.stdev(all_deltas) if len(all_deltas) > 1 else 0,
        "n_tasks": len(paired),
        "n_suites": n_suites,
    }


def power_main_effect(n_total: int, n_reps: int, sigma2_delta: float,
                      effect_size: float) -> float:
    """Power to detect the overall MCP main effect.

    Uses paired t-test framework: SE = sqrt(sigma2_delta / n_total)
    where sigma2_delta is variance of per-task deltas (using mean across reps).
    """
    # With n_reps replicates, the per-task delta variance decreases
    # sigma2_delta_eff ≈ sigma2_task_delta + sigma2_rep_delta / n_reps
    # But we use the empirical sigma2_delta which already averages across reps
    se = math.sqrt(sigma2_delta / n_total)
    return power_for_effect(effect_size, se)


def power_interaction_categorical(n_per_cell: int, n_reps: int, k_levels: int,
                                  sigma2_delta_within: float,
                                  interaction_effect: float) -> float:
    """Power to detect config x categorical moderator interaction.

    Tests whether the treatment effect differs across k levels of the moderator.
    Uses F-test approximation: the interaction has k-1 df.

    For a single contrast (one level vs another), SE for the difference in
    deltas between two levels is:
      SE = sqrt(2 * sigma2_delta_within / n_per_cell)

    For the omnibus F-test, we approximate power via the noncentrality parameter:
      lambda = n_per_cell * sum_j (delta_j - delta_bar)^2 / sigma2_delta_within
    """
    # For a pairwise contrast between any two suite-level deltas:
    se_contrast = math.sqrt(2 * sigma2_delta_within / n_per_cell)
    return power_for_effect(interaction_effect, se_contrast)


def power_interaction_continuous(n_total: int, n_reps: int,
                                sigma2_delta: float,
                                sigma2_x: float,
                                interaction_slope: float) -> float:
    """Power to detect config x continuous moderator interaction.

    The interaction slope beta_int has SE:
      SE = sqrt(sigma2_delta / (n_total * sigma2_x))

    where sigma2_x is the variance of the moderator variable across tasks.
    """
    if sigma2_x <= 0:
        return 0.0
    se = math.sqrt(sigma2_delta / (n_total * sigma2_x))
    return power_for_effect(interaction_slope, se)


def compute_moderator_variances(paired: list[dict], metadata: dict) -> dict:
    """Compute variance of continuous moderators across paired tasks."""
    # Collect moderator values for paired tasks
    mcp_scores = []
    context_lengths = []
    instruction_lengths_proxy = []

    for p in paired:
        task = p["task"]
        meta = metadata.get(task, {})
        mbs = meta.get("mcp_benefit_score", 0)
        if mbs and mbs > 0:
            mcp_scores.append(mbs)
        cl = meta.get("context_length", 0)
        if cl and cl > 0:
            context_lengths.append(math.log(cl) if cl > 0 else 0)

    return {
        "mcp_benefit_score": {
            "n": len(mcp_scores),
            "mean": statistics.mean(mcp_scores) if mcp_scores else 0,
            "variance": statistics.variance(mcp_scores) if len(mcp_scores) > 1 else 0,
        },
        "log_context_length": {
            "n": len(context_lengths),
            "mean": statistics.mean(context_lengths) if context_lengths else 0,
            "variance": statistics.variance(context_lengths) if len(context_lengths) > 1 else 0,
        },
    }


def compute_language_interaction(paired: list[dict], metadata: dict) -> dict:
    """Compute observed delta variance across language groups."""
    lang_deltas = defaultdict(list)
    for p in paired:
        meta = metadata.get(p["task"], {})
        lang = meta.get("language", "unknown")
        # Normalize multi-language to primary
        if "," in lang:
            lang = lang.split(",")[0].strip()
        lang_deltas[lang].append(p["delta"])

    lang_stats = {}
    for lang, deltas in lang_deltas.items():
        if len(deltas) >= 3:
            lang_stats[lang] = {
                "n": len(deltas),
                "mean_delta": statistics.mean(deltas),
                "std_delta": statistics.stdev(deltas),
            }
    return lang_stats


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--reps", type=int, default=3,
                        help="Replicates per task per arm (default: 3)")
    parser.add_argument("--arms", type=int, default=2,
                        help="Number of treatment arms: 2=baseline+MCP, 3=+SCIP (default: 2)")
    parser.add_argument("--alpha", type=float, default=0.05,
                        help="Significance level (default: 0.05)")
    parser.add_argument("--json", action="store_true",
                        help="Output JSON")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST_PATH.read_text())
    paired = load_paired_data(manifest)
    metadata = load_task_metadata(SELECTION_PATH)
    vc = estimate_variance_components(paired)
    mod_vars = compute_moderator_variances(paired, metadata)
    lang_stats = compute_language_interaction(paired, metadata)

    W = 120

    print("=" * W)
    print("DOE POWER CURVES — Minimum Task Counts for Moderating Effects")
    print(f"  Pilot data: {vc['n_tasks']} paired tasks across {vc['n_suites']} SDLC suites")
    print(f"  Planned replicates: {args.reps} per task per arm")
    print(f"  Treatment arms: {args.arms} ({'baseline + MCP' if args.arms == 2 else 'baseline + MCP/fuzzy + MCP/SCIP'})")
    print(f"  Alpha: {args.alpha}")
    print("=" * W)

    # --- Section 1: Empirical Variance Estimates ---
    print(f"\n  EMPIRICAL VARIANCE ESTIMATES (from {vc['n_tasks']} paired tasks)")
    print("-" * W)
    print(f"  sigma2_total (all rewards):              {vc['sigma2_total']:.4f}")
    print(f"  sigma2_between_suite:                    {vc['sigma2_between_suite']:.4f}")
    print(f"  sigma2_task_within_suite:                {vc['sigma2_task_within_suite']:.4f}")
    print(f"  sigma2_replicate:                        {vc['sigma2_replicate']:.4f}")
    print(f"  sigma2_delta (paired MCP-BL):            {vc['sigma2_delta']:.4f}")
    print(f"  sigma2_delta_within_suite (pooled):      {vc['sigma2_delta_within_suite']:.4f}")
    print(f"  Overall mean delta (MCP - BL):           {vc['overall_mean_delta']:+.4f}")
    print(f"  Overall std delta:                       {vc['overall_std_delta']:.4f}")

    print(f"\n  Per-Suite Delta Statistics:")
    print(f"  {'Suite':<18} {'n':>4} {'mean_delta':>11} {'std_delta':>11} {'sigma2_delta':>13}")
    print(f"  {'-'*57}")
    for suite in SDLC_SUITES:
        s = vc["per_suite_stats"].get(suite.replace("csb_sdlc_", "").replace("ccb_", ""), vc["per_suite_stats"].get(suite, {}))
        if not s:
            # Try with full name
            s = vc["per_suite_stats"].get(suite, {})
        if s:
            short = suite.replace("csb_sdlc_", "").replace("ccb_", "")
            print(f"  {short:<18} {s['n']:>4} {s['mean_delta']:>+11.4f} {s['std_delta']:>11.4f} {s['sigma2_delta']:>13.4f}")

    # --- Section 2: Effect Sizes We Want to Detect ---
    print(f"\n\n  EFFECT SIZES TO DETECT")
    print("-" * W)

    observed_main = abs(vc["overall_mean_delta"])
    # Observed interaction: range of per-suite deltas
    suite_deltas = [s["mean_delta"] for s in vc["per_suite_stats"].values()]
    observed_interaction_range = max(suite_deltas) - min(suite_deltas) if suite_deltas else 0
    # A reasonable interaction contrast: difference between the most positive
    # and most negative suite delta
    observed_interaction = observed_interaction_range / 2  # half-range as representative contrast

    print(f"  Observed main effect (|mean delta|):     {observed_main:.4f}")
    print(f"  Observed interaction range:              {observed_interaction_range:.4f}")
    print(f"    (best suite: {max(suite_deltas):+.4f}, worst: {min(suite_deltas):+.4f})")
    print(f"  Representative interaction contrast:     {observed_interaction:.4f}")

    # Define a grid of effect sizes to analyze
    main_effects = [0.05, 0.10, 0.15, 0.20]
    interaction_effects = [0.05, 0.10, 0.15, 0.20]
    task_counts = [30, 50, 75, 100, 125, 150, 180, 200, 250, 300, 400]

    # --- Section 3: Power Curves for Main Effect ---
    print(f"\n\n  POWER CURVES: MAIN EFFECT OF CONFIG (MCP vs Baseline)")
    print(f"  (Paired test on per-task deltas, sigma2_delta = {vc['sigma2_delta']:.4f})")
    print("-" * W)

    header = f"  {'n_total':>8}"
    for eff in main_effects:
        header += f" {'d='+str(eff):>9}"
    header += f"  {'d=obs':>9}"
    print(header)
    print(f"  {'-'*8}" + f" {'-'*9}" * (len(main_effects) + 1))

    for n in task_counts:
        row = f"  {n:>8}"
        for eff in main_effects:
            pw = power_main_effect(n, args.reps, vc["sigma2_delta"], eff)
            marker = " *" if pw >= 0.80 else "  "
            row += f" {pw:>7.3f}{marker}"
        # Observed effect
        pw_obs = power_main_effect(n, args.reps, vc["sigma2_delta"], observed_main)
        marker = " *" if pw_obs >= 0.80 else "  "
        row += f"  {pw_obs:>7.3f}{marker}"
        print(row)

    # Minimum n for each effect size
    print(f"\n  Minimum n for 80% power:")
    for eff in main_effects + [observed_main]:
        for n in range(5, 1000):
            if power_main_effect(n, args.reps, vc["sigma2_delta"], eff) >= 0.80:
                label = f"d={eff:.2f}" if eff != observed_main else f"d={eff:.4f} (observed)"
                print(f"    {label}: n >= {n}")
                break

    # --- Section 4: Power Curves for Config x SDLC Phase Interaction ---
    print(f"\n\n  POWER CURVES: CONFIG x SDLC PHASE INTERACTION")
    print(f"  (Pairwise contrast between suite-level deltas)")
    print(f"  (sigma2_delta_within_suite = {vc['sigma2_delta_within_suite']:.4f})")
    print("-" * W)

    k_suites = 9
    header = f"  {'n_total':>8} {'n/suite':>8}"
    for eff in interaction_effects:
        header += f" {'d='+str(eff):>9}"
    header += f"  {'d=obs':>9}"
    print(header)
    print(f"  {'-'*8} {'-'*8}" + f" {'-'*9}" * (len(interaction_effects) + 1))

    for n in task_counts:
        n_per = n // k_suites
        if n_per < 2:
            continue
        row = f"  {n:>8} {n_per:>8}"
        for eff in interaction_effects:
            pw = power_interaction_categorical(
                n_per, args.reps, k_suites,
                vc["sigma2_delta_within_suite"], eff
            )
            marker = " *" if pw >= 0.80 else "  "
            row += f" {pw:>7.3f}{marker}"
        # Observed
        pw_obs = power_interaction_categorical(
            n_per, args.reps, k_suites,
            vc["sigma2_delta_within_suite"], observed_interaction
        )
        marker = " *" if pw_obs >= 0.80 else "  "
        row += f"  {pw_obs:>7.3f}{marker}"
        print(row)

    print(f"\n  Minimum n_total (= n_per_suite x {k_suites}) for 80% power:")
    for eff in interaction_effects + [observed_interaction]:
        for n_per in range(2, 200):
            pw = power_interaction_categorical(
                n_per, args.reps, k_suites,
                vc["sigma2_delta_within_suite"], eff
            )
            if pw >= 0.80:
                label = f"d={eff:.2f}" if eff != observed_interaction else f"d={eff:.4f} (observed)"
                print(f"    {label}: n >= {n_per * k_suites} ({n_per}/suite)")
                break

    # --- Section 5: Power for Config x Continuous Moderator ---
    print(f"\n\n  POWER CURVES: CONFIG x CONTINUOUS MODERATOR (codebase size / complexity)")
    print("-" * W)

    # MCP benefit score as proxy for complexity/codebase characteristics
    mbs = mod_vars["mcp_benefit_score"]
    if mbs["variance"] > 0:
        print(f"\n  Moderator: MCP Benefit Score (proxy for task complexity)")
        print(f"    Available for {mbs['n']} tasks, variance = {mbs['variance']:.4f}, mean = {mbs['mean']:.3f}")
        print(f"    sigma2_delta = {vc['sigma2_delta']:.4f}")

        # The interaction slope represents: "for each unit increase in moderator,
        # how much does the MCP delta change?"
        # A slope of 0.5 means: going from mbs=0.5 to mbs=1.0, the delta increases by 0.25
        slopes = [0.2, 0.3, 0.5, 0.8, 1.0]

        header = f"\n  {'n_total':>8}"
        for s in slopes:
            header += f" {'b='+str(s):>9}"
        print(header)
        print(f"  {'-'*8}" + f" {'-'*9}" * len(slopes))

        for n in task_counts:
            row = f"  {n:>8}"
            for slope in slopes:
                pw = power_interaction_continuous(
                    n, args.reps, vc["sigma2_delta"],
                    mbs["variance"], slope
                )
                marker = " *" if pw >= 0.80 else "  "
                row += f" {pw:>7.3f}{marker}"
            print(row)

        print(f"\n  Minimum n for 80% power to detect interaction slope:")
        for slope in slopes:
            for n in range(5, 1000):
                pw = power_interaction_continuous(
                    n, args.reps, vc["sigma2_delta"],
                    mbs["variance"], slope
                )
                if pw >= 0.80:
                    print(f"    slope={slope}: n >= {n}")
                    break

    lcl = mod_vars["log_context_length"]
    if lcl["variance"] > 0:
        print(f"\n  Moderator: Log(Context Length) (proxy for codebase size)")
        print(f"    Available for {lcl['n']} tasks, variance = {lcl['variance']:.4f}")

        slopes = [0.05, 0.10, 0.15, 0.20]
        header = f"\n  {'n_total':>8}"
        for s in slopes:
            header += f" {'b='+str(s):>9}"
        print(header)
        print(f"  {'-'*8}" + f" {'-'*9}" * len(slopes))

        for n in task_counts:
            row = f"  {n:>8}"
            for slope in slopes:
                pw = power_interaction_continuous(
                    n, args.reps, vc["sigma2_delta"],
                    lcl["variance"], slope
                )
                marker = " *" if pw >= 0.80 else "  "
                row += f" {pw:>7.3f}{marker}"
            print(row)

    # --- Section 6: Language as a Moderator ---
    if lang_stats:
        print(f"\n\n  OBSERVED DELTA BY LANGUAGE (potential moderator)")
        print("-" * W)
        print(f"  {'Language':<15} {'n':>5} {'mean_delta':>11} {'std_delta':>11}")
        print(f"  {'-'*42}")
        for lang in sorted(lang_stats, key=lambda x: -lang_stats[x]["n"]):
            ls = lang_stats[lang]
            print(f"  {lang:<15} {ls['n']:>5} {ls['mean_delta']:>+11.4f} {ls['std_delta']:>11.4f}")

        # Compute observed language interaction (max delta difference)
        lang_deltas_list = [ls["mean_delta"] for ls in lang_stats.values()]
        if len(lang_deltas_list) > 1:
            lang_interaction = (max(lang_deltas_list) - min(lang_deltas_list)) / 2
            print(f"\n  Observed language interaction contrast: {lang_interaction:.4f}")
            n_langs = len(lang_stats)
            lang_pooled_var = sum(
                ls["std_delta"]**2 * (ls["n"] - 1)
                for ls in lang_stats.values()
            ) / sum(ls["n"] - 1 for ls in lang_stats.values())
            print(f"  Pooled within-language delta variance: {lang_pooled_var:.4f}")
            print(f"  Number of language groups (n >= 3): {n_langs}")

    # --- Section 7: Three-Arm Design Adjustments ---
    if args.arms == 3:
        print(f"\n\n  THREE-ARM DESIGN: Baseline + MCP/Fuzzy + MCP/SCIP")
        print("-" * W)
        print(f"""
  With 3 arms, you have two orthogonal contrasts:
    Contrast A: MCP/fuzzy vs Baseline (tool availability effect)
    Contrast B: MCP/SCIP vs MCP/fuzzy (index precision effect)

  Contrast A power is identical to the 2-arm analysis above.
  Contrast B compares two MCP arms that differ only in index quality.

  Key assumption: sigma2_delta for Contrast B (SCIP vs fuzzy) is likely
  SMALLER than for Contrast A (MCP vs baseline), because:
    - Both arms use the same MCP tools
    - Task difficulty is identical
    - Only the index backend changes

  Conservative estimate: sigma2_delta_B = 0.75 * sigma2_delta_A
  Optimistic estimate: sigma2_delta_B = 0.50 * sigma2_delta_A
  (You should update these after a pilot with SCIP data)
""")

        for scenario, factor in [("Conservative (0.75x)", 0.75),
                                  ("Optimistic (0.50x)", 0.50)]:
            sigma2_b = vc["sigma2_delta"] * factor
            print(f"  {scenario}: sigma2_delta_B = {sigma2_b:.4f}")
            print(f"  {'n_total':>8}", end="")
            for eff in [0.05, 0.10, 0.15]:
                print(f" {'d='+str(eff):>9}", end="")
            print()
            print(f"  {'-'*8}" + f" {'-'*9}" * 3)

            for n in task_counts:
                row = f"  {n:>8}"
                for eff in [0.05, 0.10, 0.15]:
                    pw = power_main_effect(n, args.reps, sigma2_b, eff)
                    marker = " *" if pw >= 0.80 else "  "
                    row += f" {pw:>7.3f}{marker}"
                print(row)

            print(f"  Min n for Contrast B at 80% power:")
            for eff in [0.05, 0.10, 0.15]:
                for n in range(5, 1000):
                    if power_main_effect(n, args.reps, sigma2_b, eff) >= 0.80:
                        print(f"    d={eff}: n >= {n}")
                        break
            print()

    # --- Section 8: Summary Recommendations ---
    print(f"\n\n  SUMMARY: RECOMMENDED TASK COUNTS")
    print("=" * W)

    # Compute minimums for each question
    recs = []

    # Q1: Overall MCP main effect at observed delta
    for n in range(5, 1000):
        if power_main_effect(n, args.reps, vc["sigma2_delta"], 0.10) >= 0.80:
            recs.append(("Main effect (d=0.10)", n, "Total tasks"))
            break

    # Q2: SDLC interaction at observed level
    for n_per in range(2, 200):
        if power_interaction_categorical(
            n_per, args.reps, k_suites,
            vc["sigma2_delta_within_suite"], 0.10
        ) >= 0.80:
            recs.append(("SDLC x Config interaction (d=0.10)", n_per * k_suites, f"{n_per}/suite x {k_suites}"))
            break

    # Q3: Continuous moderator
    if mbs["variance"] > 0:
        for n in range(5, 1000):
            if power_interaction_continuous(
                n, args.reps, vc["sigma2_delta"],
                mbs["variance"], 0.5
            ) >= 0.80:
                recs.append(("Complexity x Config (slope=0.5)", n, "Total tasks"))
                break

    # Q4: Three-arm SCIP contrast
    if args.arms == 3:
        sigma2_b = vc["sigma2_delta"] * 0.75
        for n in range(5, 1000):
            if power_main_effect(n, args.reps, sigma2_b, 0.10) >= 0.80:
                recs.append(("SCIP precision effect (d=0.10)", n, "Total tasks"))
                break

    # Combined recommendation: max across all questions
    print(f"\n  {'Question':<45} {'Min n':>6} {'Note':<25}")
    print(f"  {'-'*76}")
    for label, n, note in recs:
        print(f"  {label:<45} {n:>6} {note:<25}")

    if recs:
        max_n = max(r[1] for r in recs)
        print(f"\n  RECOMMENDATION: {max_n} tasks minimum")
        print(f"  (driven by the hardest-to-detect effect above)")

        # Account for SDLC balance
        ideal_per_suite = math.ceil(max_n / k_suites)
        print(f"\n  For balanced SDLC coverage: {ideal_per_suite}/suite x {k_suites} = {ideal_per_suite * k_suites}")
        print(f"  For Neyman-weighted coverage: redistribute based on per-suite variance")
        print(f"  (run doe_variance_analysis.py --budget {ideal_per_suite * k_suites} for optimal allocation)")

    # Model complexity summary
    n_fixed_params = 1 + 1 + 8 + 1 + 1 + 8 + 1 + 1  # intercept + config + sdlc(8) + size + complexity + config:sdlc(8) + config:size + config:complexity
    print(f"\n  MODEL COMPLEXITY:")
    print(f"    Fixed effects parameters: {n_fixed_params}")
    print(f"    (intercept + config + sdlc_phase[8] + codebase_size + complexity")
    print(f"     + config:sdlc[8] + config:size + config:complexity)")
    print(f"    Rule of thumb: 10-20 obs per parameter = {n_fixed_params*10}-{n_fixed_params*20} observations")
    print(f"    With {args.reps} reps x {args.arms} arms = {args.reps * args.arms} obs/task")
    print(f"    -> {math.ceil(n_fixed_params*15 / (args.reps * args.arms))} tasks for stable estimation (15 obs/param)")
    print(f"\n  * = power >= 0.80")
    print()


if __name__ == "__main__":
    main()
