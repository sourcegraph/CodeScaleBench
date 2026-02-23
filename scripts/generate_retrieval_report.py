#!/usr/bin/env python3
"""Generate standalone retrieval and impact report.

Consumes retrieval metric artifacts and impact analysis outputs to produce
a human-readable Markdown report summarizing coverage, retrieval quality,
utilization quality, downstream impact, and caveats.

This report is **standalone and non-ranking** in v1.

Usage:
    python3 scripts/generate_retrieval_report.py --run-dir runs/staging --all
    python3 scripts/generate_retrieval_report.py --run-dir runs/staging --all --output reports/retrieval_report.md
    python3 scripts/generate_retrieval_report.py --summary run_retrieval_summary.json --impact impact_analysis.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))


def _fmt(val, decimals=4) -> str:
    if val is None:
        return "N/A"
    if isinstance(val, float):
        return f"{val:.{decimals}f}"
    return str(val)


def _pct(val) -> str:
    if val is None:
        return "N/A"
    return f"{val * 100:.1f}%"


def generate_report(
    summary: dict | None,
    impact: dict | None,
) -> str:
    """Generate Markdown report from summary and impact analysis data."""
    lines: list[str] = []

    lines.append("# Retrieval Evaluation Report (v1)")
    lines.append("")
    lines.append("> **Status**: Standalone, non-ranking. This report evaluates retrieval quality")
    lines.append("> and downstream impact without affecting primary CCB scoring or leaderboard.")
    lines.append("")
    lines.append(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    # --- Coverage ---
    lines.append("## 1. Coverage")
    lines.append("")
    if summary:
        total = summary.get("total_event_files", 0)
        computable = summary.get("computable_tasks", 0)
        skipped = summary.get("skipped_no_ground_truth", 0)
        chunk_capable = summary.get("chunk_capable_tasks", 0)

        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Total tasks normalized | {total} |")
        lines.append(f"| Tasks with ground truth (computable) | {computable} |")
        lines.append(f"| Tasks without ground truth (skipped) | {skipped} |")
        lines.append(f"| Tasks with chunk-level GT | {chunk_capable} |")
        lines.append("")

        if skipped > 0:
            lines.append(f"**Note**: {skipped} tasks ({_pct(skipped / total if total > 0 else 0)}) lack")
            lines.append(f"file-level ground truth and are excluded from IR metric computation.")
            lines.append(f"These are typically MCP-unique discovery tasks where success is measured")
            lines.append(f"by artifact quality rather than file retrieval.")
            lines.append("")
    else:
        lines.append("*No summary data available.*")
        lines.append("")

    # --- Retrieval Quality ---
    lines.append("## 2. Retrieval Quality")
    lines.append("")
    if summary and summary.get("file_level_aggregates", {}).get("_totals", {}).get("n_tasks", 0) > 0:
        fa = summary["file_level_aggregates"]
        n = fa["_totals"]["n_tasks"]

        lines.append(f"Aggregated over **{n}** computable tasks:")
        lines.append("")
        lines.append("### File-Level IR Metrics")
        lines.append("")
        lines.append("| Metric | Mean | Median | Std |")
        lines.append("|--------|------|--------|-----|")

        for metric in ["file_recall", "mrr", "map_score", "context_efficiency"]:
            m = fa.get(metric, {})
            lines.append(f"| {metric} | {_fmt(m.get('mean'))} | {_fmt(m.get('median'))} | {_fmt(m.get('std'))} |")

        for k in [1, 3, 5, 10]:
            for prefix in ["precision", "recall", "ndcg"]:
                key = f"{prefix}@{k}"
                m = fa.get(key, {})
                if m:
                    lines.append(f"| {key} | {_fmt(m.get('mean'))} | {_fmt(m.get('median'))} | {_fmt(m.get('std'))} |")

        lines.append("")

        # TTFR
        ttfr = fa.get("ttfr_seconds", {})
        if ttfr.get("n", 0) > 0:
            lines.append("### Time to First Relevant File")
            lines.append("")
            lines.append(f"| Metric | Mean | Median | n |")
            lines.append(f"|--------|------|--------|---|")
            lines.append(f"| TTFR (seconds) | {_fmt(ttfr.get('mean'), 1)} | {_fmt(ttfr.get('median'), 1)} | {ttfr.get('n')} |")
            lines.append("")

        # Summary stats
        totals = fa["_totals"]
        lines.append("### Retrieval Volume")
        lines.append("")
        lines.append(f"| Metric | Mean |")
        lines.append(f"|--------|------|")
        lines.append(f"| Files retrieved per task | {_fmt(totals.get('mean_retrieved'), 1)} |")
        lines.append(f"| Ground truth files per task | {_fmt(totals.get('mean_ground_truth'), 1)} |")
        lines.append(f"| Overlap (retrieved ∩ GT) | {_fmt(totals.get('mean_overlap'), 1)} |")
        lines.append("")
    else:
        lines.append("*No computable tasks with file-level ground truth.*")
        lines.append("")

    # --- Utilization Quality ---
    lines.append("## 3. Utilization Quality")
    lines.append("")
    if summary and summary.get("utilization_aggregates", {}).get("n_tasks_with_probes", 0) > 0:
        ua = summary["utilization_aggregates"]
        n_probes = ua["n_tasks_with_probes"]

        lines.append(f"Utilization probes available for **{n_probes}** tasks (tasks with file write events):")
        lines.append("")
        lines.append("| Probe | Mean | Median | n |")
        lines.append("|-------|------|--------|---|")

        rfc = ua.get("util_referenced_file_correctness", {})
        if rfc.get("n", 0) > 0:
            lines.append(f"| Referenced file correctness | {_fmt(rfc.get('mean'))} | {_fmt(rfc.get('median'))} | {rfc.get('n')} |")

        rbw = ua.get("util_read_before_write_ratio", {})
        if rbw.get("n", 0) > 0:
            lines.append(f"| Read-before-write ratio | {_fmt(rbw.get('mean'))} | {_fmt(rbw.get('median'))} | {rbw.get('n')} |")

        lines.append("")
        lines.append("**Referenced file correctness** measures whether the agent wrote to ground-truth files.")
        lines.append("**Read-before-write ratio** measures whether the agent read files before modifying them.")
        lines.append("")
    else:
        lines.append("*No utilization probe data available (no tasks with file write events and ground truth).*")
        lines.append("")

    # --- Error Taxonomy ---
    lines.append("## 4. Error Taxonomy")
    lines.append("")
    if summary and summary.get("error_taxonomy_aggregates"):
        ta = summary["error_taxonomy_aggregates"]

        lines.append("### Error Label Distribution")
        lines.append("")
        lines.append("| Error Type | Mean Count | Median |")
        lines.append("|------------|-----------|--------|")

        for label in ["irrelevant_retrieval", "missed_key_evidence", "wrong_evidence_used",
                       "unused_correct_retrieval", "ambiguity_near_miss"]:
            m = ta.get(label, {})
            lines.append(f"| {label} | {_fmt(m.get('mean'), 1)} | {_fmt(m.get('median'), 1)} |")

        lines.append("")

        # Slice distributions
        slices = ta.get("slice_distributions", {})
        if slices:
            lines.append("### Calibration Slices")
            lines.append("")
            for slice_name, dist in slices.items():
                lines.append(f"**{slice_name}**: " + ", ".join(f"{k}={v}" for k, v in sorted(dist.items())))
            lines.append("")
    else:
        lines.append("*No error taxonomy data available.*")
        lines.append("")

    # --- Downstream Impact ---
    lines.append("## 5. Downstream Impact")
    lines.append("")

    if impact:
        # Correlation
        corr = impact.get("correlation_analysis", {})
        if corr.get("computable"):
            lines.append("### Correlation Analysis")
            lines.append("")
            lines.append(f"Spearman rank correlations over **{corr['n_joined']}** joined (retrieval × outcome) pairs:")
            lines.append("")
            lines.append("| Retrieval Metric | Outcome Metric | r | p | n |")
            lines.append("|-----------------|----------------|---|---|---|")

            for c in corr.get("correlations", []):
                sig = "\\*" if c["spearman_p"] < 0.05 else ""
                lines.append(
                    f"| {c['retrieval_metric']} | {c['outcome_metric']} "
                    f"| {c['spearman_r']:.3f}{sig} | {c['spearman_p']:.4f} | {c['n']} |"
                )

            lines.append("")
            lines.append("\\* = statistically significant (p < 0.05)")
            lines.append("")
            lines.append("**These are associations, not causal claims.**")
            lines.append("")
        else:
            reason = corr.get("reason", "unknown")
            lines.append(f"### Correlation Analysis: Not computable ({reason})")
            lines.append("")

        # Matched comparison
        matched = impact.get("matched_comparison", {})
        if matched.get("computable"):
            lines.append("### Matched Comparison")
            lines.append("")
            lines.append(f"Paired comparison of **{matched['n_matched_tasks']}** matched tasks")
            lines.append(f"({matched['baseline_config']} vs {matched['mcp_config']}):")
            lines.append("")
            lines.append("| Metric | Mean Δ | Median Δ | IQR | +/−/0 | n |")
            lines.append("|--------|--------|---------|-----|-------|---|")

            for key in ["reward", "file_recall", "mrr", "cost_usd", "wall_clock_seconds"]:
                d = matched.get("deltas", {}).get(key, {})
                if d.get("n", 0) > 0:
                    pnz = f"{_pct(d.get('positive_fraction'))}/{_pct(d.get('negative_fraction'))}/{_pct(d.get('zero_fraction'))}"
                    lines.append(
                        f"| {key} | {_fmt(d.get('mean_delta'))} | {_fmt(d.get('median_delta'))} "
                        f"| {_fmt(d.get('iqr'))} | {pnz} | {d['n']} |"
                    )

            lines.append("")
            lines.append("Δ = MCP − Baseline. Positive values indicate MCP improvement.")
            lines.append("")
            lines.append("**These are comparative observations, not causal claims.**")
            lines.append(f"**Unmatched tasks**: {matched.get('n_baseline_only', 0)} baseline-only, "
                         f"{matched.get('n_mcp_only', 0)} MCP-only.")
            lines.append("")
        else:
            reason = matched.get("reason", "unknown")
            lines.append(f"### Matched Comparison: Not computable ({reason})")
            lines.append("")
    else:
        lines.append("*No impact analysis data available.*")
        lines.append("")

    # --- Caveats ---
    lines.append("## 6. Caveats and Limitations")
    lines.append("")
    lines.append("- **Standalone and non-ranking**: This report does not affect primary CCB")
    lines.append("  scoring, leaderboard rankings, or verifier rewards.")
    lines.append("- **Ground truth coverage**: Tasks without file-level ground truth are excluded")
    lines.append("  from all IR metrics. MCP-unique discovery tasks typically lack file-level GT.")
    lines.append("- **Chunk-level granularity**: v1 only supports file-match granularity for")
    lines.append("  chunk-level metrics. Sub-line matching is deferred to future versions.")
    lines.append("- **Utilization probes**: Only measure file-level correctness of write actions.")
    lines.append("  They do not validate semantic correctness of written content.")
    lines.append("- **Correlation ≠ causation**: All associations are observational. Confounders")
    lines.append("  (task difficulty, instruction quality, model capability) are not controlled.")
    lines.append("- **Matched comparisons**: Require both configs to have run the same task.")
    lines.append("  Unmatched tasks are excluded, which may introduce selection bias.")
    lines.append("- **Trace completeness**: Some tasks may have incomplete traces (degraded mode).")
    lines.append("  Coverage flags indicate when data is partial or missing.")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate standalone retrieval and impact report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Input modes:\n"
            "  Mode 1: --run-dir [--all] — auto-discover summary + impact files\n"
            "  Mode 2: --summary + --impact — provide pre-computed JSON files\n"
        ),
    )
    parser.add_argument("--run-dir", type=Path, default=None, help="Run directory or parent with --all.")
    parser.add_argument("--all", action="store_true", help="Walk all runs under --run-dir.")
    parser.add_argument("--summary", type=Path, default=None, help="Path to run_retrieval_summary.json.")
    parser.add_argument("--impact", type=Path, default=None, help="Path to impact analysis JSON.")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Write Markdown to file.")
    args = parser.parse_args()

    # Load summary
    summary: dict | None = None
    if args.summary:
        summary = json.loads(args.summary.read_text())
    elif args.run_dir:
        # Auto-discover
        candidates: list[Path] = []
        if args.all:
            for rd in sorted(args.run_dir.iterdir()):
                if rd.is_dir():
                    c = rd / "retrieval_events" / "run_retrieval_summary.json"
                    if c.is_file():
                        candidates.append(c)
        else:
            c = args.run_dir / "retrieval_events" / "run_retrieval_summary.json"
            if c.is_file():
                candidates.append(c)

        if candidates:
            # Use the latest
            summary = json.loads(candidates[-1].read_text())

    # Load impact
    impact: dict | None = None
    if args.impact:
        impact = json.loads(args.impact.read_text())

    if summary is None and impact is None:
        print("No data found. Run the pipeline and impact analysis first.", file=sys.stderr)
        sys.exit(1)

    report = generate_report(summary, impact)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report)
        print(f"Report written to {args.output}", file=sys.stderr)
    else:
        print(report)


if __name__ == "__main__":
    main()
