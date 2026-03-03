#!/usr/bin/env python3
"""Suite merging power analysis for CodeScaleBench.

Computes achieved statistical power per suite, models power curves,
and evaluates proposed merge candidates.

Usage:
    python3 scripts/suite_power_analysis.py
    python3 scripts/suite_power_analysis.py --output docs/analysis/suite_merge_analysis.md
"""

import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from extract_v2_report_data import scan_all_tasks, TASK_META


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------

def required_n(sigma: float, delta: float = 0.05, alpha: float = 0.05, power: float = 0.80) -> int:
    """Sample size needed for paired t-test to detect delta with given power."""
    z_alpha = 1.96   # two-sided
    z_beta = 0.842   # 80% power
    n = math.ceil(((z_alpha + z_beta) * sigma / delta) ** 2)
    return max(n, 2)


def achieved_power(n: int, sigma: float, delta: float = 0.05, alpha: float = 0.05) -> float:
    """Achieved power of paired t-test given sample size and variance."""
    if sigma <= 0:
        return 1.0
    ncp = delta * math.sqrt(n) / sigma
    z_alpha = 1.96
    power = 1.0 - 0.5 * (1 + math.erf((z_alpha - ncp) / math.sqrt(2)))
    return max(0.0, min(1.0, power))


def power_curve(sigma: float, delta: float = 0.05, max_n: int = 200) -> list[tuple[int, float]]:
    """Power as a function of n for given sigma and delta."""
    points = []
    for n in range(2, max_n + 1):
        p = achieved_power(n, sigma, delta)
        points.append((n, p))
    return points


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def compute_suite_deltas(records: list[dict]) -> dict[str, list[float]]:
    """Compute paired reward deltas grouped by suite."""
    grouped = defaultdict(lambda: defaultdict(list))
    for r in records:
        grouped[r["task_name"]][r["config_type"]].append(r["reward"])

    deltas_by_suite: dict[str, list[float]] = defaultdict(list)
    for task_name, by_config in grouped.items():
        if "baseline" not in by_config or "mcp" not in by_config:
            continue
        bl_mean = statistics.mean(by_config["baseline"])
        mcp_mean = statistics.mean(by_config["mcp"])
        delta = mcp_mean - bl_mean

        meta = TASK_META.get(task_name, {})
        bm = meta.get("benchmark", "unknown")
        deltas_by_suite[bm].append(delta)

    return dict(deltas_by_suite)


def analyze_suite(name: str, deltas: list[float]) -> dict:
    """Compute power stats for a single suite."""
    n = len(deltas)
    mean_d = statistics.mean(deltas)
    sigma = statistics.stdev(deltas) if n > 1 else 0.0
    power = achieved_power(n, sigma)
    n_needed = required_n(sigma) if sigma > 0 else n
    return {
        "name": name,
        "n": n,
        "mean_delta": round(mean_d, 4),
        "sigma": round(sigma, 4),
        "power": round(power, 4),
        "n_needed_80pct": n_needed,
        "deltas": deltas,
    }


# ---------------------------------------------------------------------------
# Merge candidates
# ---------------------------------------------------------------------------

MERGE_CANDIDATES = [
    {
        "name": "crossrepo_merged",
        "label": "Cross-Repo Discovery (merged)",
        "suites": ["csb_org_crossrepo", "csb_org_crossrepo_tracing"],
        "rationale": "Both involve tracing dependencies/symbols across repo boundaries. "
                     "crossrepo_tracing is a superset of crossrepo's scope.",
    },
    {
        "name": "crossorg_merged",
        "label": "Cross-Org & Org Context (merged)",
        "suites": ["csb_org_crossorg", "csb_org_org"],
        "rationale": "Both require understanding organizational code structure. "
                     "crossorg adds the multi-org dimension but the core skill is the same.",
    },
    {
        "name": "compliance_platform",
        "label": "Compliance & Platform Knowledge (merged)",
        "suites": ["csb_org_compliance", "csb_org_platform"],
        "rationale": "Both test policy/configuration understanding across codebases. "
                     "Similar variance profiles and non-overlapping repos.",
    },
    {
        "name": "understand_design",
        "label": "Understand & Design (merged)",
        "suites": ["csb_sdlc_understand", "csb_sdlc_design"],
        "rationale": "Both are comprehension-heavy tasks (understand asks questions, "
                     "design produces plans). Neither modifies code.",
    },
]


def evaluate_merges(deltas_by_suite: dict[str, list[float]]) -> list[dict]:
    """Evaluate each merge candidate."""
    results = []
    for candidate in MERGE_CANDIDATES:
        all_deltas = []
        components = []
        for s in candidate["suites"]:
            suite_deltas = deltas_by_suite.get(s, [])
            all_deltas.extend(suite_deltas)
            components.append({"suite": s, "n": len(suite_deltas)})

        merged = analyze_suite(candidate["name"], all_deltas)
        # Compare with individual suite powers
        individual_powers = []
        for s in candidate["suites"]:
            sd = deltas_by_suite.get(s, [])
            if sd:
                individual_powers.append(analyze_suite(s, sd))

        results.append({
            "candidate": candidate,
            "merged": merged,
            "components": components,
            "individual": individual_powers,
            "power_gain": merged["power"] - max(ip["power"] for ip in individual_powers) if individual_powers else 0,
        })
    return results


# ---------------------------------------------------------------------------
# Markdown report generation
# ---------------------------------------------------------------------------

def generate_report(suite_stats: list[dict], merge_results: list[dict]) -> str:
    """Generate markdown analysis report."""
    lines = [
        "# Suite Merging Power Analysis",
        "",
        "## Summary",
        "",
        "This analysis evaluates the statistical power of CodeScaleBench's 20 suites",
        "to detect a meaningful MCP effect (delta = 0.05) and proposes merges to",
        "improve power without losing analytical granularity.",
        "",
        "**Key finding:** Only {} of 20 suites achieve 80% power at delta=0.05.".format(
            sum(1 for s in suite_stats if s["power"] >= 0.80)
        ),
        "Merging related low-power suites improves coverage while preserving the",
        "ability to report fine-grained results as sub-analyses.",
        "",
        "## Current Suite Power (delta = 0.05, alpha = 0.05, two-sided)",
        "",
        "| Suite | n | Mean Delta | Sigma | Power | N needed (80%) |",
        "|-------|---|-----------|-------|-------|---------------|",
    ]

    for s in sorted(suite_stats, key=lambda x: -x["power"]):
        power_str = f"**{s['power']:.1%}**" if s["power"] >= 0.80 else f"{s['power']:.1%}"
        lines.append(
            f"| {s['name']} | {s['n']} | {s['mean_delta']:+.4f} | "
            f"{s['sigma']:.4f} | {power_str} | {s['n_needed_80pct']} |"
        )

    lines.extend([
        "",
        "## Power Interpretation",
        "",
        "- **High power (>80%):** Can reliably detect delta=0.05 effects. Results are conclusive.",
        "- **Moderate power (50-80%):** May detect effects but has meaningful false negative risk.",
        "- **Low power (<50%):** Suite-level conclusions are unreliable. Large effects may still be visible.",
        "",
        "High-variance suites (sigma > 0.20) like understand, security, and incident need",
        "50-170+ tasks each to achieve 80% power. This is impractical to add — merging is the",
        "better strategy.",
        "",
        "## Proposed Merges",
        "",
    ])

    for mr in merge_results:
        c = mr["candidate"]
        m = mr["merged"]
        lines.append(f"### {c['label']}")
        lines.append("")
        lines.append(f"**Rationale:** {c['rationale']}")
        lines.append("")
        lines.append("| Config | n | Sigma | Power | N needed |")
        lines.append("|--------|---|-------|-------|----------|")
        for ind in mr["individual"]:
            lines.append(
                f"| {ind['name']} (current) | {ind['n']} | "
                f"{ind['sigma']:.4f} | {ind['power']:.1%} | {ind['n_needed_80pct']} |"
            )
        power_str = f"**{m['power']:.1%}**" if m["power"] >= 0.80 else f"{m['power']:.1%}"
        lines.append(
            f"| **{c['name']}** (merged) | **{m['n']}** | "
            f"**{m['sigma']:.4f}** | {power_str} | **{m['n_needed_80pct']}** |"
        )
        lines.append("")
        gain = mr["power_gain"]
        if gain > 0:
            lines.append(f"Power gain from merging: **+{gain:.1%}**")
        else:
            lines.append(f"Power change from merging: {gain:+.1%} (variance increase offsets sample size gain)")
        lines.append("")

    lines.extend([
        "## Implementation: Merged Suite View",
        "",
        "The merge is a **reporting-layer change only**. Existing tasks, runs, and per-suite",
        "breakdowns remain intact. The extract script gains a `SUITE_MERGE_MAP` that aggregates",
        "paired stats under merged suite names while preserving the original suite as a sub-field.",
        "",
        "### Reporting hierarchy",
        "",
        "```",
        "Overall (n=370)",
        "  ├── SDLC (n=150)",
        "  │   ├── understand_design (merged, n=24)",
        "  │   │   ├── understand (n=10)",
        "  │   │   └── design (n=14)",
        "  │   ├── feature (n=23)",
        "  │   ├── fix (n=26)",
        "  │   └── ... (7 more)",
        "  └── Org (n=220)",
        "      ├── crossrepo_merged (n=36)",
        "      │   ├── crossrepo (n=14)",
        "      │   └── crossrepo_tracing (n=22)",
        "      ├── crossorg_merged (n=30)",
        "      │   ├── crossorg (n=15)",
        "      │   └── org (n=15)",
        "      ├── compliance_platform (n=36)",
        "      │   ├── compliance (n=18)",
        "      │   └── platform (n=18)",
        "      └── ... (5 more)",
        "```",
        "",
        "### DO NOT merge",
        "",
        "- **security (n=24):** Strongest MCP signal (+0.113), merging would dilute it",
        "- **incident (n=20):** Second strongest MCP signal (+0.108), keep separate",
        "- **migration (n=26):** Already large enough, distinct task profile",
        "- **onboarding (n=28):** Already large enough, distinct task profile",
        "- **domain (n=20):** Low variance (sigma=0.072), already near 80% power",
        "",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Suite merging power analysis")
    parser.add_argument("--output", "-o", type=Path, help="Write markdown report to file")
    parser.add_argument("--json", action="store_true", help="Also output JSON data")
    args = parser.parse_args()

    print("Scanning runs/official/...", file=sys.stderr)
    records = scan_all_tasks()
    print(f"  Found {len(records)} evaluations", file=sys.stderr)

    deltas_by_suite = compute_suite_deltas(records)

    # Analyze each suite
    suite_stats = []
    for suite_name in sorted(deltas_by_suite.keys()):
        suite_stats.append(analyze_suite(suite_name, deltas_by_suite[suite_name]))

    # Evaluate merges
    merge_results = evaluate_merges(deltas_by_suite)

    # Print summary
    header = f"{'Suite':<30} {'n':>4} {'mean_d':>8} {'sigma':>8} {'power':>7} {'N@80%':>6}"
    print(header)
    print("-" * len(header))
    for s in sorted(suite_stats, key=lambda x: -x["power"]):
        print(f"{s['name']:<30} {s['n']:>4} {s['mean_delta']:>+8.4f} "
              f"{s['sigma']:>8.4f} {s['power']:>6.1%} {s['n_needed_80pct']:>6}")

    print("\nMERGE CANDIDATES:")
    print(header)
    print("-" * len(header))
    for mr in merge_results:
        m = mr["merged"]
        components = " + ".join(f"{c['suite']}({c['n']})" for c in mr["components"])
        print(f"{m['name']:<30} {m['n']:>4} {m['mean_delta']:>+8.4f} "
              f"{m['sigma']:>8.4f} {m['power']:>6.1%} {m['n_needed_80pct']:>6}  [{components}]")

    # Generate report
    report = generate_report(suite_stats, merge_results)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report)
        print(f"\nReport written to {args.output}", file=sys.stderr)
    else:
        print("\n" + "=" * 70)
        print(report)

    if args.json:
        # Strip raw deltas for JSON output
        for s in suite_stats:
            del s["deltas"]
        json_data = {
            "suite_stats": suite_stats,
            "merge_results": [
                {
                    "name": mr["candidate"]["name"],
                    "suites": mr["candidate"]["suites"],
                    "merged_n": mr["merged"]["n"],
                    "merged_sigma": mr["merged"]["sigma"],
                    "merged_power": mr["merged"]["power"],
                    "power_gain": mr["power_gain"],
                }
                for mr in merge_results
            ],
        }
        json_path = (args.output or Path("suite_power_analysis")).with_suffix(".json")
        json_path.write_text(json.dumps(json_data, indent=2) + "\n")
        print(f"JSON written to {json_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
