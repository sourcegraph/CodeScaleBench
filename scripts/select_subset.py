#!/usr/bin/env python3
"""Select a representative subset of benchmark tasks for validation runs.

Stratified sampling across suites, languages, difficulties, and codebase
LOC bands to produce subsets that preserve the full benchmark's distribution.

Suites are classified by observed MCP effect-size direction so the subset
covers the full spectrum: high-positive, near-zero, negative, and mixed.

Usage:
    python3 scripts/select_subset.py --size 80 --seed 42
    python3 scripts/select_subset.py --size 40 --name quick --seed 7
    python3 scripts/select_subset.py --size 80 --seed 42 --power-report

Outputs:
    configs/subset_tasks_{name}.json   (selection-file for run_selected_tasks.sh)
    configs/subset_tasks_{name}.txt    (plain task-id list, one per line)
"""

import argparse
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_FILE = ROOT / "configs" / "selected_benchmark_tasks.json"
OFFICIAL = ROOT / "runs" / "official"

# ---------------------------------------------------------------------------
# Suite effect-size classification (from observed Haiku run deltas)
# ---------------------------------------------------------------------------

# Buckets assigned from the empirical mean deltas in runs/official/.
# Updated if --refresh-deltas is passed (but defaults are stable).
SUITE_BUCKETS = {
    # High positive: mean_delta > 0.05
    "csb_org_incident": "high_positive",
    "csb_org_security": "high_positive",
    "csb_sdlc_understand": "high_positive",
    "csb_sdlc_fix": "high_positive",
    # Near zero: |mean_delta| <= 0.03
    "csb_org_compliance": "near_zero",
    "csb_org_crossorg": "near_zero",
    "csb_org_crossrepo": "near_zero",
    "csb_org_domain": "near_zero",
    "csb_org_migration": "near_zero",
    "csb_sdlc_feature": "near_zero",
    "csb_sdlc_secure": "near_zero",
    "csb_sdlc_document": "near_zero",
    "csb_sdlc_test": "near_zero",
    # Negative: mean_delta < -0.03
    "csb_org_platform": "negative",
    "csb_sdlc_debug": "negative",
    "csb_sdlc_design": "negative",
    "csb_sdlc_refactor": "negative",
    # Mixed / moderate positive: 0.03 < mean_delta <= 0.05
    "csb_org_crossrepo_tracing": "mixed",
    "csb_org_onboarding": "mixed",
    "csb_org_org": "mixed",
}

# Minimum tasks per suite in subset (for power).  If a suite has fewer tasks
# in the full benchmark, we take all of them.
MIN_PER_SUITE = 3


def loc_band(loc: int | None) -> str:
    """Bucket repositories by cloc-derived code lines."""
    if loc is None:
        return "unknown"
    if loc < 400_000:
        return "<400K"
    if loc < 2_000_000:
        return "400K-2M"
    if loc < 8_000_000:
        return "2M-8M"
    if loc < 40_000_000:
        return "8M-40M"
    return ">40M"


def primary_language(lang: str) -> str:
    """Collapse multi-language entries to primary."""
    if not lang or lang == "unknown":
        return "other"
    first = lang.split(",")[0].strip()
    # Group rare languages
    if first in ("python", "go", "java", "cpp", "typescript", "javascript", "rust", "c"):
        return first
    return "other"


# ---------------------------------------------------------------------------
# Load full task list
# ---------------------------------------------------------------------------

def load_tasks() -> list[dict]:
    with open(TASKS_FILE) as f:
        data = json.load(f)
    return data["tasks"]


# ---------------------------------------------------------------------------
# Allocation: proportional to suite size with per-bucket minimums
# ---------------------------------------------------------------------------

def allocate_per_suite(tasks: list[dict], target: int) -> dict[str, int]:
    """Decide how many tasks to sample from each suite.

    Strategy:
    1. Each effect-size bucket gets proportional share of target.
    2. Within each bucket, allocate proportionally to suite size.
    3. Enforce MIN_PER_SUITE floor (capped at suite size).
    4. Adjust to hit exact target via largest-remainder method.
    """
    suite_sizes = Counter(t["benchmark"] for t in tasks)
    total = sum(suite_sizes.values())

    # Bucket membership
    buckets: dict[str, list[str]] = defaultdict(list)
    for suite in suite_sizes:
        bucket = SUITE_BUCKETS.get(suite, "near_zero")
        buckets[bucket].append(suite)

    # Step 1: proportional allocation per suite
    raw: dict[str, float] = {}
    for suite, n in suite_sizes.items():
        raw[suite] = target * (n / total)

    # Step 2: apply floor
    alloc: dict[str, int] = {}
    for suite, n in suite_sizes.items():
        floor = min(MIN_PER_SUITE, n)
        alloc[suite] = max(floor, int(raw[suite]))

    # Step 3: largest-remainder adjustment to hit target exactly
    current_total = sum(alloc.values())
    if current_total < target:
        # Add to suites with largest fractional remainders
        remainders = {s: raw[s] - alloc[s] for s in alloc}
        for s in sorted(remainders, key=remainders.get, reverse=True):
            if current_total >= target:
                break
            if alloc[s] < suite_sizes[s]:
                alloc[s] += 1
                current_total += 1
    elif current_total > target:
        # Remove from suites with smallest fractional remainders
        remainders = {s: raw[s] - alloc[s] for s in alloc}
        for s in sorted(remainders, key=remainders.get):
            if current_total <= target:
                break
            if alloc[s] > MIN_PER_SUITE and alloc[s] > 1:
                alloc[s] -= 1
                current_total -= 1

    return alloc


# ---------------------------------------------------------------------------
# Stratified sampling within each suite
# ---------------------------------------------------------------------------

def sample_suite(suite_tasks: list[dict], n: int, rng: random.Random) -> list[dict]:
    """Pick n tasks from a suite, stratified by language and LOC band.

    We build strata as (primary_language, loc_band) pairs and sample
    proportionally from each stratum.  If a stratum is too small we
    take all of it and redistribute.
    """
    if n >= len(suite_tasks):
        return list(suite_tasks)

    # Build strata
    strata: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in suite_tasks:
        lang = primary_language(t.get("language", "other"))
        lb = loc_band(t.get("repo_approx_loc"))
        strata[(lang, lb)].append(t)

    selected: list[dict] = []
    remaining_n = n
    remaining_strata = dict(strata)

    # Proportional draw per stratum
    while remaining_n > 0 and remaining_strata:
        total_in_strata = sum(len(v) for v in remaining_strata.values())
        draws: dict[tuple, int] = {}
        for key, items in remaining_strata.items():
            draws[key] = max(1, round(remaining_n * len(items) / total_in_strata))

        new_remaining: dict[tuple, list[dict]] = {}
        for key, items in remaining_strata.items():
            take = min(draws.get(key, 0), len(items), remaining_n)
            chosen = rng.sample(items, take)
            selected.extend(chosen)
            remaining_n -= take
            leftover = [t for t in items if t not in chosen]
            if leftover:
                new_remaining[key] = leftover

        remaining_strata = new_remaining

    # Trim if rounding overshot
    if len(selected) > n:
        selected = rng.sample(selected, n)

    return selected


# ---------------------------------------------------------------------------
# Power validation
# ---------------------------------------------------------------------------

def load_suite_sigmas() -> dict[str, float]:
    """Load observed sigma per suite from official runs."""
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from extract_v2_report_data import scan_all_tasks, TASK_META

        records = scan_all_tasks()
        grouped = defaultdict(lambda: defaultdict(list))
        for r in records:
            grouped[r["task_name"]][r["config_type"]].append(r["reward"])

        suite_deltas: dict[str, list[float]] = defaultdict(list)
        for task_name, by_config in grouped.items():
            if "baseline" not in by_config or "mcp" not in by_config:
                continue
            bl_mean = statistics.mean(by_config["baseline"])
            mcp_mean = statistics.mean(by_config["mcp"])
            delta = mcp_mean - bl_mean
            meta = TASK_META.get(task_name, {})
            bm = meta.get("benchmark", "unknown")
            suite_deltas[bm].append(delta)

        sigmas = {}
        for suite, deltas in suite_deltas.items():
            if len(deltas) > 1:
                sigmas[suite] = statistics.stdev(deltas)
        return sigmas
    except Exception as e:
        print(f"Warning: could not load run data for power analysis: {e}", file=sys.stderr)
        return {}


def achieved_power(n: int, sigma: float, delta: float = 0.05) -> float:
    if sigma <= 0:
        return 1.0
    ncp = delta * math.sqrt(n) / sigma
    z_alpha = 1.96
    power = 1.0 - 0.5 * (1 + math.erf((z_alpha - ncp) / math.sqrt(2)))
    return max(0.0, min(1.0, power))


def power_report(alloc: dict[str, int], sigmas: dict[str, float],
                  selected: list[dict]) -> str:
    lines = [
        "",
        "Power Analysis (detect delta=0.05, alpha=0.05):",
        "",
        "Per-suite (individual suite detection):",
        f"  {'Suite':<35} {'n':>4}  {'sigma':>6}  {'power':>6}  {'status'}",
        "  " + "-" * 63,
    ]
    warnings = 0
    for suite in sorted(alloc):
        n = alloc[suite]
        sigma = sigmas.get(suite, 0.0)
        if sigma > 0:
            pwr = achieved_power(n, sigma)
            status = "OK" if pwr >= 0.50 else "LOW"
            if pwr < 0.50:
                warnings += 1
            lines.append(f"  {suite:<35} {n:>4}  {sigma:>6.3f}  {pwr:>6.3f}  {status}")
        else:
            lines.append(f"  {suite:<35} {n:>4}  {'N/A':>6}  {'N/A':>6}  NO DATA")

    # Bucket-level power (aggregate across suites in same effect-size bucket)
    lines.extend(["", "Per effect-size bucket (recommended analysis level for subsets):",
                   f"  {'Bucket':<20} {'n':>4}  {'sigma':>6}  {'power':>6}  {'status'}",
                   "  " + "-" * 50])

    bucket_tasks: dict[str, list[str]] = defaultdict(list)
    for suite, n in alloc.items():
        bucket = SUITE_BUCKETS.get(suite, "near_zero")
        bucket_tasks[bucket].extend([suite] * n)

    # We need per-task deltas grouped by bucket — approximate with pooled sigma
    for bucket in ["high_positive", "mixed", "near_zero", "negative"]:
        bucket_suites = [s for s, b in SUITE_BUCKETS.items() if b == bucket]
        n_bucket = sum(alloc.get(s, 0) for s in bucket_suites)
        # Pool sigmas: weighted average of variances
        total_var_weight = 0.0
        total_weight = 0
        for s in bucket_suites:
            ns = alloc.get(s, 0)
            sig = sigmas.get(s, 0.0)
            if sig > 0 and ns > 0:
                total_var_weight += (ns - 1) * sig**2
                total_weight += (ns - 1)
        if total_weight > 0:
            pooled_sigma = math.sqrt(total_var_weight / total_weight)
            pwr = achieved_power(n_bucket, pooled_sigma)
            status = "OK" if pwr >= 0.50 else "LOW"
            lines.append(f"  {bucket:<20} {n_bucket:>4}  {pooled_sigma:>6.3f}  {pwr:>6.3f}  {status}")
        else:
            lines.append(f"  {bucket:<20} {n_bucket:>4}  {'N/A':>6}  {'N/A':>6}  NO DATA")

    # Overall pooled
    total_n = sum(alloc.values())
    all_sigmas = [s for s in sigmas.values() if s > 0]
    if all_sigmas:
        overall_sigma = statistics.mean(all_sigmas)
        overall_power = achieved_power(total_n, overall_sigma)
        lines.extend(["", f"Overall pooled: n={total_n}, sigma={overall_sigma:.3f}, "
                       f"power={overall_power:.3f}"])

    lines.append("")
    if warnings:
        lines.append(
            f"Note: {warnings}/20 suites below 50% individual power (expected for subsets). "
            "Use bucket-level analysis for subset validation runs."
        )
    else:
        lines.append("All suites meet minimum power threshold (50%).")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_outputs(selected: list[dict], name: str, alloc: dict[str, int],
                  sigmas: dict[str, float], seed: int, show_power: bool):
    """Write JSON selection file and plain-text task list."""
    out_dir = ROOT / "configs"

    # Build JSON in same format as selected_benchmark_tasks.json
    per_suite = Counter(t["benchmark"] for t in selected)
    output = {
        "metadata": {
            "title": f"CodeScaleBench Subset: {name}",
            "version": "1.0",
            "generated_by": "scripts/select_subset.py",
            "seed": seed,
            "total_selected": len(selected),
            "source": "configs/selected_benchmark_tasks.json",
            "per_suite": dict(sorted(per_suite.items())),
            "effect_size_buckets": {
                "high_positive": sorted(s for s, b in SUITE_BUCKETS.items() if b == "high_positive"),
                "near_zero": sorted(s for s, b in SUITE_BUCKETS.items() if b == "near_zero"),
                "negative": sorted(s for s, b in SUITE_BUCKETS.items() if b == "negative"),
                "mixed": sorted(s for s, b in SUITE_BUCKETS.items() if b == "mixed"),
            },
        },
        "tasks": sorted(selected, key=lambda t: (t["benchmark"], t["task_id"])),
    }

    json_path = out_dir / f"subset_tasks_{name}.json"
    with open(json_path, "w") as f:
        json.dump(output, f, indent=2)
        f.write("\n")

    # Plain text list
    txt_path = out_dir / f"subset_tasks_{name}.txt"
    task_ids = sorted(t["task_id"] for t in selected)
    with open(txt_path, "w") as f:
        f.write("\n".join(task_ids) + "\n")

    print(f"Selected {len(selected)} tasks (seed={seed})")
    print(f"  JSON: {json_path.relative_to(ROOT)}")
    print(f"  TXT:  {txt_path.relative_to(ROOT)}")

    # Distribution summary
    print(f"\nSuite allocation:")
    for suite in sorted(per_suite):
        bucket = SUITE_BUCKETS.get(suite, "?")
        print(f"  {suite:<35} {per_suite[suite]:>3}  ({bucket})")

    lang_dist = Counter(primary_language(t.get("language", "")) for t in selected)
    print(f"\nLanguages: {dict(sorted(lang_dist.items(), key=lambda x: -x[1]))}")

    diff_dist = Counter(t.get("difficulty", "?") for t in selected)
    print(f"Difficulties: {dict(diff_dist)}")

    loc_dist = Counter(loc_band(t.get("repo_approx_loc")) for t in selected)
    print(f"LOC bands: {dict(loc_dist)}")

    if show_power:
        print(power_report(alloc, sigmas, selected))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Select a representative task subset for validation runs."
    )
    parser.add_argument("--size", type=int, default=80,
                        help="Target number of tasks (default: 80)")
    parser.add_argument("--name", type=str, default=None,
                        help="Subset name for output files (default: n{size})")
    parser.add_argument("--seed", type=int, default=42,
                        help="Random seed for reproducibility")
    parser.add_argument("--power-report", action="store_true",
                        help="Print power analysis for the selected subset")
    args = parser.parse_args()

    if args.name is None:
        args.name = f"n{args.size}"

    tasks = load_tasks()
    total = len(tasks)

    if args.size >= total:
        print(f"Requested size ({args.size}) >= total tasks ({total}). Use full benchmark.")
        sys.exit(1)

    if args.size < 20:
        print(f"Requested size ({args.size}) too small for meaningful stratification.")
        sys.exit(1)

    rng = random.Random(args.seed)

    # Group by suite
    by_suite: dict[str, list[dict]] = defaultdict(list)
    for t in tasks:
        by_suite[t["benchmark"]].append(t)

    # Adjust MIN_PER_SUITE if target is too small for the floor
    global MIN_PER_SUITE
    n_suites = len(by_suite)
    if args.size < MIN_PER_SUITE * n_suites:
        MIN_PER_SUITE = max(1, args.size // n_suites)
        print(f"Note: reduced MIN_PER_SUITE to {MIN_PER_SUITE} to fit target size.")

    # Allocate
    alloc = allocate_per_suite(tasks, args.size)

    # Sample
    selected: list[dict] = []
    for suite, n in alloc.items():
        chosen = sample_suite(by_suite[suite], n, rng)
        selected.extend(chosen)

    # Load sigmas for power report
    sigmas = {}
    if args.power_report:
        sigmas = load_suite_sigmas()

    write_outputs(selected, args.name, alloc, sigmas, args.seed, args.power_report)


if __name__ == "__main__":
    main()
