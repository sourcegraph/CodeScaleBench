#!/usr/bin/env python3
"""Enterprise report generator for CodeContextBench.

Orchestrates all enterprise metric sub-scripts and produces:
- enterprise_report.json  (top-level envelope per enterprise_report_schema.json)
- ENTERPRISE_REPORT.md    (four-section technical + workflow + executive + failure report)
- EXECUTIVE_SUMMARY.md    (under 500 words, headline metrics)
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ensure sibling modules are importable (same pattern as other scripts/)
sys.path.insert(0, str(Path(__file__).resolve().parent))

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sub-report runners — import programmatically, fall back gracefully
# ---------------------------------------------------------------------------


def _run_workflow_metrics() -> Optional[dict]:
    """Run workflow metrics extraction and return output dict."""
    try:
        from workflow_metrics import (
            build_output,
            compute_category_aggregates,
            compute_category_deltas,
            compute_navigation_summary,
            scan_workflow_metrics,
        )

        tasks = scan_workflow_metrics()
        if not tasks:
            logger.warning("workflow_metrics: no tasks found")
            return None
        cat_agg = compute_category_aggregates(tasks)
        cat_delta = compute_category_deltas(cat_agg)
        nav_summary = compute_navigation_summary(tasks)
        return build_output(tasks, cat_agg, cat_delta, nav_summary)
    except Exception:
        logger.warning("workflow_metrics: failed to run", exc_info=True)
        return None


def _run_economic_analysis() -> Optional[dict]:
    """Run economic analysis and return output dict."""
    try:
        from economic_analysis import (
            build_output,
            compute_cost_comparison,
            compute_per_config,
            compute_roi_summary,
            scan_economic_data,
        )

        tasks = scan_economic_data()
        if not tasks:
            logger.warning("economic_analysis: no tasks found")
            return None
        per_config = compute_per_config(tasks)
        cost_comp = compute_cost_comparison(tasks)
        roi = compute_roi_summary(per_config, cost_comp)
        return build_output(tasks, per_config, cost_comp, roi, include_comparison=True)
    except Exception:
        logger.warning("economic_analysis: failed to run", exc_info=True)
        return None


def _run_reliability_analysis() -> Optional[dict]:
    """Run reliability analysis and return output dict."""
    try:
        from reliability_analysis import (
            build_output,
            compute_cross_suite_consistency,
            compute_failure_clusters,
            compute_per_suite_config_stats,
            compute_reliability_floor,
            load_task_metadata,
            scan_task_rewards,
        )

        metadata = load_task_metadata()
        tasks = scan_task_rewards()
        if not tasks:
            logger.warning("reliability_analysis: no tasks found")
            return None
        psc = compute_per_suite_config_stats(tasks)
        cross = compute_cross_suite_consistency(psc)
        floor = compute_reliability_floor(psc)
        clusters = compute_failure_clusters(tasks, metadata)
        return build_output(psc, cross, floor, clusters)
    except Exception:
        logger.warning("reliability_analysis: failed to run", exc_info=True)
        return None


def _run_failure_analysis() -> Optional[dict]:
    """Run failure analysis and return output dict."""
    try:
        from failure_analysis import (
            build_output,
            classify_failures,
            compute_aggregates,
            compute_context_attribution,
            compute_context_summary,
            compute_residual_limitations,
            scan_failed_tasks,
        )

        all_tasks, failed_tasks = scan_failed_tasks()
        if not failed_tasks:
            logger.warning("failure_analysis: no failed tasks found")
            return None
        classified = classify_failures(failed_tasks)
        attributed = compute_context_attribution(all_tasks, classified)
        aggregates = compute_aggregates(attributed)
        context_summary = compute_context_summary(attributed)
        residuals = compute_residual_limitations(attributed)
        return build_output(attributed, aggregates, context_summary, residuals)
    except Exception:
        logger.warning("failure_analysis: failed to run", exc_info=True)
        return None


def _run_governance_report() -> Optional[dict]:
    """Run governance evaluator if available."""
    try:
        from governance_evaluator import main as gov_main  # noqa: F401

        # governance_evaluator.py doesn't exist yet — this will ImportError
        logger.info("governance_evaluator found — running")
        return None  # placeholder
    except ImportError:
        logger.info("governance_evaluator not available — skipping")
        return None
    except Exception:
        logger.warning("governance_evaluator: failed to run", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------


def _get_ccb_version() -> str:
    """Get version string from git describe."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            capture_output=True, text=True, timeout=10,
            cwd=Path(__file__).resolve().parent.parent,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _count_total_tasks(sections: dict[str, Optional[dict]]) -> int:
    """Count unique tasks across all sections."""
    task_keys: set[str] = set()
    for section in sections.values():
        if section is None:
            continue
        per_task = section.get("per_task", [])
        for t in per_task:
            name = t.get("task_name", "")
            config = t.get("config", "")
            task_keys.add(f"{name}:{config}")
    return len(task_keys)


def _get_configs(sections: dict[str, Optional[dict]]) -> list[str]:
    """Collect unique config names from all sections."""
    configs: set[str] = set()
    for section in sections.values():
        if section is None:
            continue
        for t in section.get("per_task", []):
            if c := t.get("config"):
                configs.add(c)
        # Also check per_config keys (economic)
        if pc := section.get("per_config"):
            configs.update(pc.keys())
        # Also check reliability per_suite_config
        if psc := section.get("per_suite_config"):
            for suite_data in psc.values():
                configs.update(suite_data.keys())
    return sorted(configs)


# ---------------------------------------------------------------------------
# Executive summary computation
# ---------------------------------------------------------------------------


def _compute_executive_summary(sections: dict[str, Optional[dict]]) -> dict[str, Any]:
    """Compute executive summary from available section data."""
    summary: dict[str, Any] = {
        "headline_metric": "",
        "reliability_improvement_pct": None,
        "time_savings_estimate": None,
        "economic_efficiency": None,
        "reliability_ci": None,
        "top_residual_limitation": None,
        "governance_readiness": "Pending — governance evaluation not yet implemented",
    }

    # --- Reliability improvement (from economic or reliability sections) ---
    econ = sections.get("economic_metrics")
    if econ and (roi := econ.get("roi_summary")):
        bl_rate = roi.get("baseline_pass_rate")
        sg_rate = roi.get("sg_full_pass_rate")
        if bl_rate is not None and sg_rate is not None and bl_rate > 0:
            delta_pct = (sg_rate - bl_rate) / bl_rate * 100
            summary["reliability_improvement_pct"] = round(delta_pct, 1)
            summary["headline_metric"] = (
                f"Context infrastructure improves agent task success by "
                f"{abs(round(delta_pct, 1))}%"
            )
        # Economic efficiency
        bl_cost = roi.get("baseline_avg_cost_usd")
        sg_cost = roi.get("sg_full_avg_cost_usd")
        cost_delta = roi.get("cost_delta_pct")
        pass_delta = roi.get("pass_rate_delta")
        if bl_cost is not None and sg_cost is not None:
            summary["economic_efficiency"] = (
                f"SG_full costs ${sg_cost:.2f}/task vs baseline ${bl_cost:.2f}/task "
                f"({'+' if cost_delta and cost_delta > 0 else ''}"
                f"{cost_delta:.0f}% cost delta) with "
                f"{'+' if pass_delta and pass_delta > 0 else ''}"
                f"{pass_delta:.1f}pp pass rate improvement"
            )

    # Fallback headline if economic data unavailable
    if not summary["headline_metric"]:
        reliability = sections.get("reliability_metrics")
        if reliability and (rf := reliability.get("reliability_floor")):
            for config, data in rf.items():
                if "sourcegraph_full" in config:
                    mean_r = data.get("mean_reward", 0)
                    summary["headline_metric"] = (
                        f"SG_full achieves {mean_r:.1%} mean task success rate"
                    )
                    break
        if not summary["headline_metric"]:
            summary["headline_metric"] = "Enterprise metrics report generated"

    # --- Time savings (from workflow metrics) ---
    wf = sections.get("workflow_metrics")
    if wf and (deltas := wf.get("category_deltas")):
        total_saved = 0.0
        n_categories = 0
        for cat, data in deltas.items():
            saved = data.get("estimated_time_saved_seconds")
            if saved is not None:
                total_saved += saved
                n_categories += 1
        if n_categories > 0:
            avg_saved_min = total_saved / n_categories / 60
            summary["time_savings_estimate"] = (
                f"Modeled estimate: {avg_saved_min:.1f} engineer-minutes saved "
                f"per task on average across {n_categories} workflow categories"
            )

    # --- Reliability CI (from reliability_analysis) ---
    reliability = sections.get("reliability_metrics")
    if reliability and (psc := reliability.get("per_suite_config")):
        # Collect all SG_full CIs across suites
        all_lower: list[float] = []
        all_upper: list[float] = []
        total_n = 0
        total_pass = 0.0
        for suite_data in psc.values():
            sg_data = suite_data.get("sourcegraph_full")
            if sg_data:
                n = sg_data.get("n_tasks", 0)
                mean = sg_data.get("mean_reward", 0)
                total_n += n
                total_pass += mean * n
                lo = sg_data.get("ci_95_lower")
                hi = sg_data.get("ci_95_upper")
                if lo is not None and hi is not None:
                    all_lower.append(lo * n)
                    all_upper.append(hi * n)
        if total_n > 0:
            overall_rate = total_pass / total_n
            # Weighted average CI
            if all_lower and all_upper:
                w_lo = sum(all_lower) / total_n
                w_hi = sum(all_upper) / total_n
                summary["reliability_ci"] = (
                    f"SG_full overall pass rate: {overall_rate:.1%} "
                    f"(weighted 95% CI: [{w_lo:.2f}, {w_hi:.2f}])"
                )
            else:
                summary["reliability_ci"] = (
                    f"SG_full overall pass rate: {overall_rate:.1%} "
                    f"(insufficient data for aggregate CI)"
                )

    # --- Top residual limitation (from failure analysis) ---
    fa = sections.get("failure_analysis")
    if fa and (residuals := fa.get("residual_limitations")):
        if residuals:
            top = max(residuals, key=lambda r: r.get("count_in_sg_full", 0))
            summary["top_residual_limitation"] = (
                f"{top['label']} ({top['count_in_sg_full']} tasks in SG_full)"
            )

    # --- Governance readiness ---
    gov = sections.get("governance_report")
    if gov:
        summary["governance_readiness"] = "Available — see governance report section"

    return summary


# ---------------------------------------------------------------------------
# Markdown report generation
# ---------------------------------------------------------------------------


def _generate_enterprise_report_md(
    sections: dict[str, Optional[dict]],
    exec_summary: dict[str, Any],
    metadata: dict[str, Any],
) -> str:
    """Generate ENTERPRISE_REPORT.md with four sections."""
    lines: list[str] = []
    lines.append("# CodeContextBench Enterprise Report")
    lines.append("")
    lines.append(f"*Generated: {metadata['generated_at']}*")
    lines.append(f"*Version: {metadata['ccb_version']}*")
    lines.append(f"*Total tasks: {metadata['total_tasks']} | "
                 f"Configs: {', '.join(metadata['configs_compared'])}*")
    lines.append("")

    # Section 1: Technical Report
    lines.append("## 1. Technical Report")
    lines.append("")
    econ = sections.get("economic_metrics")
    if econ and (pc := econ.get("per_config")):
        lines.append("### Task Success Rates by Configuration")
        lines.append("")
        lines.append("| Config | Tasks | Passed | Pass Rate | Avg Cost/Task |")
        lines.append("|--------|-------|--------|-----------|---------------|")
        for config, data in sorted(pc.items()):
            n = data.get("n_tasks", 0)
            passed = data.get("tasks_passed", 0)
            rate = data.get("pass_rate", 0)
            cost = data.get("avg_cost_per_task_usd", 0)
            lines.append(f"| {config} | {n} | {passed} | {rate:.1%} | ${cost:.2f} |")
        lines.append("")

    wf = sections.get("workflow_metrics")
    if wf and (nav := wf.get("navigation_summary")):
        lines.append("### MCP Tool Usage by Configuration")
        lines.append("")
        lines.append("| Config | Tasks | Mean MCP Calls | Mean Search Queries | "
                     "Mean Navigation Ratio |")
        lines.append("|--------|-------|---------------|--------------------|-"
                     "--------------------|")
        for config, data in sorted(nav.items()):
            n = data.get("n_tasks", 0)
            mcp = data.get("mean_mcp_call_count", 0) or 0
            search = data.get("mean_search_query_count", 0) or 0
            nav_ratio = data.get("mean_navigation_ratio", 0) or 0
            lines.append(f"| {config} | {n} | {mcp:.1f} | {search:.1f} | "
                         f"{nav_ratio:.3f} |")
        lines.append("")

    # Section 2: Workflow Report
    lines.append("## 2. Workflow Report")
    lines.append("")
    if wf and (deltas := wf.get("category_deltas")):
        lines.append("### Time Savings by Workflow Category")
        lines.append("")
        lines.append("*All time projections are MODELED ESTIMATES. "
                     "See docs/WORKFLOW_METRICS.md for methodology.*")
        lines.append("")
        lines.append("| Category | Baseline Mean (s) | SG_full Mean (s) | "
                     "Time Saved (s) | Change |")
        lines.append("|----------|-------------------|------------------|"
                     "----------------|--------|")
        for cat, data in sorted(deltas.items()):
            bl_t = data.get("baseline_mean_time_seconds")
            sg_t = data.get("sg_full_mean_time_seconds")
            saved = data.get("estimated_time_saved_seconds")
            pct = data.get("estimated_time_saved_pct")
            bl_str = f"{bl_t:.0f}" if bl_t is not None else "N/A"
            sg_str = f"{sg_t:.0f}" if sg_t is not None else "N/A"
            saved_str = f"{saved:.0f}" if saved is not None else "N/A"
            pct_str = f"{pct:+.1f}%" if pct is not None else "N/A"
            lines.append(f"| {cat} | {bl_str} | {sg_str} | {saved_str} | "
                         f"{pct_str} |")
        lines.append("")

    if wf and (nav := wf.get("navigation_summary")):
        lines.append("### Navigation Reduction")
        lines.append("")
        bl_nav = nav.get("baseline", {}).get("mean_navigation_ratio")
        sg_nav = nav.get("sourcegraph_full", {}).get("mean_navigation_ratio")
        if bl_nav is not None and sg_nav is not None:
            lines.append(f"- Baseline navigation ratio: {bl_nav:.3f}")
            lines.append(f"- SG_full navigation ratio: {sg_nav:.3f}")
            if bl_nav > 0:
                change = (sg_nav - bl_nav) / bl_nav * 100
                lines.append(f"- Change: {change:+.1f}%")
        lines.append("")

    # Section 3: Executive Report
    lines.append("## 3. Executive Report")
    lines.append("")
    lines.append(f"**{exec_summary['headline_metric']}**")
    lines.append("")
    if exec_summary.get("time_savings_estimate"):
        lines.append(f"- **Time Savings**: {exec_summary['time_savings_estimate']}")
    if exec_summary.get("economic_efficiency"):
        lines.append(f"- **Economic Efficiency**: {exec_summary['economic_efficiency']}")
    if exec_summary.get("reliability_ci"):
        lines.append(f"- **Reliability**: {exec_summary['reliability_ci']}")
    if exec_summary.get("top_residual_limitation"):
        lines.append(f"- **Top Residual Limitation**: "
                     f"{exec_summary['top_residual_limitation']}")
    lines.append(f"- **Governance**: {exec_summary['governance_readiness']}")
    lines.append("")

    # Section 4: Failure Analysis Dossier
    lines.append("## 4. Failure Analysis Dossier")
    lines.append("")
    fa = sections.get("failure_analysis")
    if fa:
        if agg := fa.get("aggregate"):
            lines.append("### Failure Mode Distribution")
            lines.append("")
            lines.append("| Failure Mode | Count |")
            lines.append("|-------------|-------|")
            for mode, count in sorted(agg.items(), key=lambda x: -x[1]):
                lines.append(f"| {mode} | {count} |")
            lines.append("")

        if cs := fa.get("context_summary"):
            lines.append("### Context Attribution Summary")
            lines.append("")
            lines.append("| Impact | Count |")
            lines.append("|--------|-------|")
            for impact, count in sorted(cs.items(), key=lambda x: -x[1]):
                lines.append(f"| {impact} | {count} |")
            lines.append("")

        if residuals := fa.get("residual_limitations"):
            lines.append("### Residual Limitations (SG_full)")
            lines.append("")
            for r in residuals:
                lines.append(f"- **{r['label']}** ({r['count_in_sg_full']} tasks): "
                             f"{r['description']}")
            lines.append("")
    else:
        lines.append("*Failure analysis data not available.*")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*All projections marked as modeled estimates. "
                 "Measured metrics are derived directly from benchmark execution data.*")

    return "\n".join(lines)


def _generate_executive_summary_md(
    exec_summary: dict[str, Any],
    metadata: dict[str, Any],
    sections: dict[str, Optional[dict]],
) -> str:
    """Generate EXECUTIVE_SUMMARY.md (under 500 words)."""
    lines: list[str] = []
    lines.append("# CodeContextBench Executive Summary")
    lines.append("")
    lines.append(f"*{metadata['generated_at']} | {metadata['ccb_version']} | "
                 f"{metadata['total_tasks']} tasks*")
    lines.append("")

    # Headline
    lines.append(f"## {exec_summary['headline_metric']}")
    lines.append("")

    # Key findings
    lines.append("### Key Findings")
    lines.append("")

    # Pass rate improvement
    imp = exec_summary.get("reliability_improvement_pct")
    econ = sections.get("economic_metrics")
    if imp is not None and econ:
        roi = econ.get("roi_summary", {})
        bl_rate = roi.get("baseline_pass_rate", 0)
        sg_rate = roi.get("sg_full_pass_rate", 0)
        lines.append(
            f"Context-augmented agents (SG_full) achieve a **{sg_rate:.1%} task success "
            f"rate** compared to **{bl_rate:.1%} baseline**, a "
            f"**{abs(imp):.1f}% relative improvement** "
            f"({'measured' if imp > 0 else 'measured — regression'})."
        )
        lines.append("")

    # Time savings
    if ts := exec_summary.get("time_savings_estimate"):
        lines.append(f"**Time Savings** (modeled): {ts}")
        lines.append("")

    # Economic efficiency
    if ee := exec_summary.get("economic_efficiency"):
        lines.append(f"**Economic Efficiency** (measured cost, modeled ROI): {ee}")
        lines.append("")

    # Reliability
    if ci := exec_summary.get("reliability_ci"):
        lines.append(f"**Reliability** (measured): {ci}")
        lines.append("")

    # Failure modes
    if rl := exec_summary.get("top_residual_limitation"):
        lines.append(f"**Top Residual Limitation**: {rl}")
        lines.append("")

    # Context impact
    fa = sections.get("failure_analysis")
    if fa and (cs := fa.get("context_summary")):
        resolved = cs.get("context_resolved", 0)
        no_impact = cs.get("context_no_impact", 0)
        total_failed = sum(cs.values())
        if total_failed > 0:
            lines.append(
                f"Of {total_failed} failed tasks analyzed, context infrastructure "
                f"**resolved {resolved}** ({resolved/total_failed:.0%}) and had "
                f"**no impact on {no_impact}** ({no_impact/total_failed:.0%})."
            )
            lines.append("")

    # Governance
    lines.append(f"**Governance**: {exec_summary['governance_readiness']}")
    lines.append("")

    # Methodology note
    lines.append("---")
    lines.append("")
    lines.append(
        "*This summary distinguishes measured metrics (derived from benchmark "
        "execution data) from modeled estimates (projected using developer "
        "productivity multipliers). All cost figures reflect hypothetical API "
        "pricing, not actual subscription costs. "
        "See ENTERPRISE_REPORT.md for full methodology.*"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Schema validation (soft dependency)
# ---------------------------------------------------------------------------


def _validate_against_schema(report: dict, schema_path: Path) -> bool:
    """Validate report against JSON Schema if jsonschema is available."""
    try:
        import jsonschema  # type: ignore[import-untyped]

        schema = json.loads(schema_path.read_text())
        jsonschema.validate(instance=report, schema=schema)
        logger.info("Schema validation passed: %s", schema_path.name)
        return True
    except ImportError:
        logger.info("jsonschema not installed — skipping validation")
        return True
    except Exception as e:
        logger.warning("Schema validation failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate all enterprise reports: enterprise_report.json, "
            "ENTERPRISE_REPORT.md, EXECUTIVE_SUMMARY.md."
        )
    )
    parser.add_argument(
        "--output-dir", default="reports/", metavar="DIR",
        help="Output directory for reports (default: reports/)",
    )
    parser.add_argument(
        "--profile", "-p", metavar="PROFILE",
        help=(
            "Generate ICP-specific report for a customer profile. "
            "Options: legacy_modernization, platform_saas, security_compliance, "
            "ai_forward, platform_consolidation. Supports partial match."
        ),
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args()


def _run_icp_profile_analysis(
    profile_id: str,
    sections: dict[str, Optional[dict]],
) -> Optional[dict]:
    """Run ICP profile analysis against available section data."""
    try:
        from icp_profiles import compute_profile_metrics, get_profile

        profile = get_profile(profile_id)
        if not profile:
            logger.warning("Unknown ICP profile: %s", profile_id)
            return None

        return compute_profile_metrics(
            profile_id=profile["id"],
            workflow_data=sections.get("workflow_metrics"),
            economic_data=sections.get("economic_metrics"),
            reliability_data=sections.get("reliability_metrics"),
            failure_data=sections.get("failure_analysis"),
            governance_data=sections.get("governance_report"),
        )
    except ImportError:
        logger.warning("icp_profiles module not found")
        return None
    except Exception:
        logger.warning("ICP profile analysis failed", exc_info=True)
        return None


def _generate_profile_report_md(
    profile_data: dict,
    sections: dict[str, Optional[dict]],
    metadata: dict[str, Any],
) -> str:
    """Generate a profile-specific markdown report."""
    try:
        from icp_profiles import ICP_PROFILES, generate_profile_report_section
    except ImportError:
        return ""

    pid = profile_data.get("profile_id", "unknown")
    profile = ICP_PROFILES.get(pid, {})
    report_title = profile_data.get("report_title", "ICP Profile Report")

    lines: list[str] = []
    lines.append(f"# {report_title}")
    lines.append("")
    lines.append(f"*Generated: {metadata['generated_at']}*")
    lines.append(f"*Profile: {profile_data.get('profile_label', pid)}*")
    lines.append(f"*Suites evaluated: {', '.join(profile_data.get('suites_evaluated', []))}*")
    lines.append("")

    # Headline
    headline = profile_data.get("headline")
    if headline:
        lines.append(f"## {headline}")
        lines.append("")

    # Description
    desc = profile.get("description", "")
    if desc:
        lines.append(f"> {desc}")
        lines.append("")

    # Profile section (thresholds, pain points, sales enablement)
    lines.append(generate_profile_report_section(profile_data))

    # Metrics detail
    metrics = profile_data.get("metrics", {})

    # Workflow deltas for this profile
    if deltas := metrics.get("workflow_deltas"):
        lines.append("### Workflow Impact (Profile-Filtered)")
        lines.append("")
        lines.append("| Category | Baseline (s) | SG_full (s) | Saved (s) | Change |")
        lines.append("|----------|-------------|-------------|-----------|--------|")
        for cat, data in sorted(deltas.items()):
            bl_t = data.get("baseline_mean_time_seconds")
            sg_t = data.get("sg_full_mean_time_seconds")
            saved = data.get("estimated_time_saved_seconds")
            pct = data.get("estimated_time_saved_pct")
            bl_str = f"{bl_t:.0f}" if bl_t is not None else "N/A"
            sg_str = f"{sg_t:.0f}" if sg_t is not None else "N/A"
            saved_str = f"{saved:.0f}" if saved is not None else "N/A"
            pct_str = f"{pct:+.1f}%" if pct is not None else "N/A"
            lines.append(
                f"| {cat} | {bl_str} | {sg_str} | {saved_str} | {pct_str} |"
            )
        lines.append("")

    # Economic summary for profile suites
    if econ_sum := metrics.get("economic_summary"):
        lines.append("### Economic Impact (Profile-Filtered)")
        lines.append("")
        lines.append("| Config | Tasks | Pass Rate | Avg Cost/Task |")
        lines.append("|--------|-------|-----------|---------------|")
        for cfg, data in sorted(econ_sum.items()):
            n = data.get("n_tasks", 0)
            rate = data.get("pass_rate")
            cost = data.get("avg_cost_usd")
            rate_str = f"{rate:.1%}" if rate is not None else "N/A"
            cost_str = f"${cost:.2f}" if cost is not None else "N/A"
            lines.append(f"| {cfg} | {n} | {rate_str} | {cost_str} |")
        lines.append("")

    # Failure summary for profile suites
    if fail_sum := metrics.get("failure_summary"):
        n_fail = fail_sum.get("n_failures", 0)
        if n_fail > 0:
            lines.append(f"### Failure Analysis ({n_fail} failures in profile suites)")
            lines.append("")
            modes = fail_sum.get("failure_modes", {})
            if modes:
                lines.append("| Failure Mode | Count |")
                lines.append("|-------------|-------|")
                for mode, count in sorted(modes.items(), key=lambda x: -x[1]):
                    lines.append(f"| {mode} | {count} |")
                lines.append("")
            ctx = fail_sum.get("context_impact", {})
            if ctx:
                lines.append("| Context Impact | Count |")
                lines.append("|---------------|-------|")
                for impact, count in sorted(ctx.items(), key=lambda x: -x[1]):
                    lines.append(f"| {impact} | {count} |")
                lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        f"*Report generated for {profile_data.get('profile_label', 'Unknown')} profile. "
        f"All projections marked as modeled estimates.*"
    )

    return "\n".join(lines)


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Run all sub-reports
    print("Running enterprise report generation...")
    sections: dict[str, Optional[dict]] = {}

    print("  [1/5] Workflow metrics...", end=" ", flush=True)
    sections["workflow_metrics"] = _run_workflow_metrics()
    print("OK" if sections["workflow_metrics"] else "skipped")

    print("  [2/5] Economic analysis...", end=" ", flush=True)
    sections["economic_metrics"] = _run_economic_analysis()
    print("OK" if sections["economic_metrics"] else "skipped")

    print("  [3/5] Reliability analysis...", end=" ", flush=True)
    sections["reliability_metrics"] = _run_reliability_analysis()
    print("OK" if sections["reliability_metrics"] else "skipped")

    print("  [4/5] Failure analysis...", end=" ", flush=True)
    sections["failure_analysis"] = _run_failure_analysis()
    print("OK" if sections["failure_analysis"] else "skipped")

    print("  [5/5] Governance report...", end=" ", flush=True)
    sections["governance_report"] = _run_governance_report()
    print("OK" if sections["governance_report"] else "skipped")

    available = sum(1 for v in sections.values() if v is not None)
    print(f"\n{available}/{len(sections)} sub-reports available.")

    # ICP profile analysis (if requested)
    profile_data: Optional[dict] = None
    if args.profile:
        print(f"\n  [ICP] Profile analysis: {args.profile}...", end=" ", flush=True)
        profile_data = _run_icp_profile_analysis(args.profile, sections)
        if profile_data:
            sections["icp_profile"] = profile_data
            print("OK")
        else:
            print("skipped")

    # Metadata
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "ccb_version": _get_ccb_version(),
        "total_tasks": _count_total_tasks(sections),
        "configs_compared": _get_configs(sections),
    }

    # Executive summary
    exec_summary = _compute_executive_summary(sections)

    # Assemble envelope
    report: dict[str, Any] = {
        **metadata,
        "sections": sections,
        "executive_summary": exec_summary,
    }

    # Validate against schema
    schema_path = Path(__file__).resolve().parent.parent / "schemas" / "enterprise_report_schema.json"
    if schema_path.exists():
        _validate_against_schema(report, schema_path)

    # Write JSON
    json_path = output_dir / "enterprise_report.json"
    json_path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Wrote {json_path}")

    # Write ENTERPRISE_REPORT.md
    report_md = _generate_enterprise_report_md(sections, exec_summary, metadata)
    md_path = output_dir / "ENTERPRISE_REPORT.md"
    md_path.write_text(report_md + "\n")
    print(f"Wrote {md_path}")

    # Write EXECUTIVE_SUMMARY.md
    exec_md = _generate_executive_summary_md(exec_summary, metadata, sections)
    exec_path = output_dir / "EXECUTIVE_SUMMARY.md"
    exec_path.write_text(exec_md + "\n")
    print(f"Wrote {exec_path}")

    # Write profile-specific report (if requested)
    if profile_data:
        profile_md = _generate_profile_report_md(profile_data, sections, metadata)
        pid = profile_data.get("profile_id", "profile")
        profile_path = output_dir / f"PROFILE_REPORT_{pid.upper()}.md"
        profile_path.write_text(profile_md + "\n")
        print(f"Wrote {profile_path}")

    print("\nDone.")


if __name__ == "__main__":
    main()
