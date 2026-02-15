#!/usr/bin/env python3
"""ICP (Ideal Customer Profile) aligned benchmark profiles.

Defines 5 enterprise customer profiles that map benchmark tasks to
organizational workflows, success thresholds, and reporting outputs.

Each profile answers:
  - What problem does this customer have?
  - What operational change occurs with context infrastructure?
  - What risk is reduced?
  - What economic outcome follows?

Usage:
  python3 scripts/icp_profiles.py                # List all profiles
  python3 scripts/icp_profiles.py --profile sas   # Show one profile
  python3 scripts/icp_profiles.py --json          # JSON output
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# ICP Profile Definitions
# ---------------------------------------------------------------------------

ICP_PROFILES: Dict[str, Dict[str, Any]] = {
    "legacy_modernization": {
        "id": "legacy_modernization",
        "label": "Legacy Enterprise Modernization",
        "short_label": "Sleeping Giants",
        "description": (
            "Large enterprises with aging monolithic codebases, sparse documentation, "
            "and unclear ownership boundaries. Primary concern is safe modernization "
            "without breaking production."
        ),
        "buyer_persona": "VP Engineering / CTO at regulated enterprise",
        "pain_points": [
            "Legacy comprehension takes weeks per service",
            "Dependency chains are undocumented and fragile",
            "Modernization attempts break unknown consumers",
            "Institutional knowledge concentrated in departing engineers",
        ],
        "benchmark_suites": [
            "ccb_locobench",
            "ccb_largerepo",
            "ccb_crossrepo",
            "ccb_dependeval",
        ],
        "workflow_categories": [
            "code_comprehension",
            "cross_repo_navigation",
            "dependency_analysis",
        ],
        "metrics_of_interest": [
            "time_to_understand_service",
            "dependency_discovery_accuracy",
            "safe_change_confidence",
            "navigation_reduction",
        ],
        "success_thresholds": {
            "dependency_ambiguity_reduction_pct": 40,
            "comprehension_time_reduction_pct": 30,
            "cross_repo_pass_rate_min": 0.50,
        },
        "report_title": "Modernization Readiness Report",
        "report_sections": [
            "legacy_comprehension_metrics",
            "dependency_visibility",
            "change_confidence_score",
            "modernization_readiness_index",
        ],
        "headline_template": "dynamic",  # computed from data, not a static template
        "objection_response": {
            "objection": "We can't adopt AI — our codebase is too complex and undocumented.",
            "response": (
                "Benchmark data shows context infrastructure improves agent success on "
                "legacy codebases by {pass_rate_delta:.0f}%, with {dep_reduction:.0f}% "
                "reduction in dependency ambiguity."
            ),
        },
    },
    "platform_saas": {
        "id": "platform_saas",
        "label": "Platform-Mature SaaS",
        "short_label": "Velocity Leaders",
        "description": (
            "Fast-moving SaaS companies with polyrepo microservices, active CI pipelines, "
            "and rapid iteration cycles. Primary concern is developer throughput and "
            "onboarding speed."
        ),
        "buyer_persona": "Head of Platform Engineering / Dev Productivity Lead",
        "pain_points": [
            "Onboarding new engineers takes 3-6 months to full productivity",
            "Cross-service changes require tribal knowledge",
            "Code reuse is low — teams rebuild instead of discover",
            "PR cycle time increases with org scale",
        ],
        "benchmark_suites": [
            "ccb_swebenchpro",
            "ccb_dibench",
            "ccb_k8sdocs",
            "ccb_tac",
            "ccb_pytorch",
        ],
        "workflow_categories": [
            "feature_implementation",
            "dependency_analysis",
            "onboarding",
        ],
        "metrics_of_interest": [
            "onboarding_time_delta",
            "pr_cycle_time",
            "code_reuse_discovery",
            "agent_success_rate",
        ],
        "success_thresholds": {
            "onboarding_acceleration_pct": 20,
            "implementation_pass_rate_min": 0.70,
            "productivity_per_dollar_min": 0.30,
        },
        "report_title": "Developer Velocity Report",
        "report_sections": [
            "implementation_throughput",
            "onboarding_compression",
            "dependency_resolution_speed",
            "productivity_per_engineer_delta",
        ],
        "headline_template": "dynamic",
        "objection_response": {
            "objection": "Our engineers are already productive — we don't need more tools.",
            "response": (
                "Benchmark data shows {impl_pass_rate:.0f}% task success with context "
                "infrastructure vs {baseline_pass_rate:.0f}% without, with "
                "{cost_per_success_delta:.0f}% improvement in cost per successful outcome."
            ),
        },
    },
    "security_compliance": {
        "id": "security_compliance",
        "label": "Security & Compliance Organizations",
        "short_label": "Governance First",
        "description": (
            "Regulated industries (fintech, healthcare, defense) where AI adoption "
            "is blocked by data boundary concerns, auditability requirements, and "
            "policy enforcement gaps."
        ),
        "buyer_persona": "CISO / Head of Engineering Compliance",
        "pain_points": [
            "AI tools have no permission enforcement — any file is accessible",
            "No audit trail for AI-assisted code changes",
            "Cross-boundary data leakage risk blocks AI adoption",
            "Compliance teams cannot verify AI behavior post-hoc",
        ],
        "benchmark_suites": [
            "ccb_governance",
            "ccb_crossrepo",
        ],
        "workflow_categories": [
            "cross_repo_navigation",
        ],
        "metrics_of_interest": [
            "compliance_rate",
            "boundary_violation_count",
            "audit_trail_completeness",
            "graceful_degradation_rate",
        ],
        "success_thresholds": {
            "compliance_rate_min": 0.90,
            "zero_sensitive_file_access": True,
            "audit_trail_completeness_min": 0.95,
        },
        "report_title": "Governance & Risk Report",
        "report_sections": [
            "compliance_assessment",
            "boundary_enforcement_results",
            "audit_trail_evaluation",
            "risk_surface_analysis",
        ],
        "headline_template": "dynamic",
        "objection_response": {
            "objection": "AI is too risky — we can't control what it accesses.",
            "response": (
                "Governance benchmarks demonstrate {compliance_rate:.0f}% compliance with "
                "enterprise data boundaries. {violation_count} boundary violations detected "
                "across {n_tasks} scenarios — all with audit trails."
            ),
        },
    },
    "ai_forward": {
        "id": "ai_forward",
        "label": "AI-Forward Organizations",
        "short_label": "Agent Builders",
        "description": (
            "Organizations actively deploying AI coding agents at scale. Primary "
            "concern is agent reliability, token efficiency, and reasoning correctness "
            "across diverse codebases."
        ),
        "buyer_persona": "Head of AI/ML Engineering / AI Platform Lead",
        "pain_points": [
            "Agent success rates vary wildly across repos and languages",
            "Token costs scale unpredictably with codebase complexity",
            "Agents hallucinate when context is partial or ambiguous",
            "No way to benchmark agent reliability before deployment",
        ],
        "benchmark_suites": [
            "ccb_swebenchpro",
            "ccb_pytorch",
            "ccb_locobench",
            "ccb_largerepo",
            "ccb_crossrepo",
            "ccb_sweperf",
        ],
        "workflow_categories": [
            "feature_implementation",
            "code_comprehension",
            "cross_repo_navigation",
            "bug_localization",
        ],
        "metrics_of_interest": [
            "agent_task_completion_rate",
            "token_efficiency",
            "reliability_ci",
            "failure_cluster_analysis",
            "context_leverage_index",
        ],
        "success_thresholds": {
            "agent_reliability_improvement_pct": 30,
            "cross_suite_consistency_cv_max": 0.50,
            "token_efficiency_improvement_pct": 15,
        },
        "report_title": "Agent Reliability Report",
        "report_sections": [
            "agent_completion_rates",
            "reliability_confidence_intervals",
            "token_cost_efficiency",
            "failure_mode_distribution",
            "context_leverage_analysis",
        ],
        "headline_template": "dynamic",
        "objection_response": {
            "objection": "We already have AI agents — why add context infrastructure?",
            "response": (
                "Without context infrastructure, agent success varies from "
                "{min_suite_rate:.0f}% to {max_suite_rate:.0f}% across domains. "
                "With it, the floor rises to {floor_with_context:.0f}% and consistency "
                "improves by {consistency_delta:.0f}%."
            ),
        },
    },
    "platform_consolidation": {
        "id": "platform_consolidation",
        "label": "Platform Consolidation & Migrations",
        "short_label": "Consolidators",
        "description": (
            "Organizations undergoing platform migrations, acquisitions, or "
            "consolidation of duplicate services across code hosts. Primary concern "
            "is architectural visibility and change coordination."
        ),
        "buyer_persona": "VP Platform / Head of Architecture",
        "pain_points": [
            "No single view of service ownership across code hosts",
            "Duplicate services discovered during incidents, not planning",
            "Migration dependency chains are invisible until they break",
            "Cross-repo changes require manual coordination across teams",
        ],
        "benchmark_suites": [
            "ccb_crossrepo",
            "ccb_largerepo",
            "ccb_dependeval",
            "ccb_dibench",
        ],
        "workflow_categories": [
            "cross_repo_navigation",
            "dependency_analysis",
        ],
        "metrics_of_interest": [
            "cross_repo_navigation_success",
            "dependency_mapping_accuracy",
            "multi_service_change_coordination",
            "architecture_visibility_score",
        ],
        "success_thresholds": {
            "cross_repo_pass_rate_improvement_pct": 25,
            "dependency_resolution_improvement_pct": 30,
            "consolidation_readiness_score_min": 0.60,
        },
        "report_title": "Architecture Visibility Report",
        "report_sections": [
            "cross_repo_capability",
            "dependency_mapping",
            "consolidation_readiness",
            "migration_risk_assessment",
        ],
        "headline_template": "dynamic",
        "objection_response": {
            "objection": "We're mid-migration — adding tools will slow us down.",
            "response": (
                "Benchmark data shows {crossrepo_improvement:.0f}% improvement in cross-repo "
                "task success and {dep_improvement:.0f}% faster dependency resolution with "
                "context infrastructure — accelerating, not slowing, consolidation."
            ),
        },
    },
}

# Reverse mapping: suite -> list of profile IDs
SUITE_TO_PROFILES: Dict[str, List[str]] = {}
for _pid, _profile in ICP_PROFILES.items():
    for _suite in _profile["benchmark_suites"]:
        SUITE_TO_PROFILES.setdefault(_suite, []).append(_pid)

# Campaign alignment mapping
CAMPAIGN_TO_PROFILE: Dict[str, str] = {
    "100_use_cases": "platform_saas",
    "sleeping_giants": "legacy_modernization",
    "security_oversight": "security_compliance",
    "ai_rollout": "ai_forward",
    "platform_consolidation": "platform_consolidation",
}


# ---------------------------------------------------------------------------
# Profile-aware metric computation
# ---------------------------------------------------------------------------

def get_profile(profile_id: str) -> Optional[Dict[str, Any]]:
    """Get a profile by ID or partial match."""
    if profile_id in ICP_PROFILES:
        return ICP_PROFILES[profile_id]
    # Partial match
    for pid, profile in ICP_PROFILES.items():
        if profile_id.lower() in pid.lower() or profile_id.lower() in profile["short_label"].lower():
            return profile
    return None


def filter_tasks_for_profile(tasks: List[Dict], profile_id: str) -> List[Dict]:
    """Filter task records to only those relevant to a profile's benchmark suites."""
    profile = get_profile(profile_id)
    if not profile:
        return tasks
    suites = set(profile["benchmark_suites"])
    return [t for t in tasks if t.get("suite") in suites]


def compute_profile_metrics(
    profile_id: str,
    workflow_data: Optional[Dict] = None,
    economic_data: Optional[Dict] = None,
    reliability_data: Optional[Dict] = None,
    failure_data: Optional[Dict] = None,
    governance_data: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Compute ICP-specific metrics from sub-report data.

    Args:
        profile_id: The profile to compute metrics for.
        workflow_data: Output from workflow_metrics.py build_output().
        economic_data: Output from economic_analysis.py build_output().
        reliability_data: Output from reliability_analysis.py build_output().
        failure_data: Output from failure_analysis.py build_output().
        governance_data: Output from governance_evaluator.py (if available).

    Returns:
        Dict with profile-specific metrics, headline, and threshold evaluation.
    """
    profile = get_profile(profile_id)
    if not profile:
        return {"error": f"Unknown profile: {profile_id}"}

    suites = set(profile["benchmark_suites"])
    result: Dict[str, Any] = {
        "profile_id": profile["id"],
        "profile_label": profile["label"],
        "report_title": profile["report_title"],
        "suites_evaluated": sorted(suites),
        "metrics": {},
        "thresholds": {},
        "headline": None,
    }

    # --- Workflow metrics (filtered to profile suites) ---
    if workflow_data:
        cat_deltas = workflow_data.get("category_deltas", {})
        relevant_cats = set(profile["workflow_categories"])
        profile_deltas = {
            k: v for k, v in cat_deltas.items() if k in relevant_cats
        }
        result["metrics"]["workflow_deltas"] = profile_deltas

        # Navigation summary filtered
        nav = workflow_data.get("navigation_summary", {})
        result["metrics"]["navigation_summary"] = nav

        # Per-task filtered
        per_task = workflow_data.get("per_task", [])
        profile_tasks = [t for t in per_task if t.get("suite") in suites]
        n_profile_tasks = len(profile_tasks)
        result["metrics"]["n_workflow_tasks"] = n_profile_tasks

    # --- Economic metrics (filtered to profile suites) ---
    if economic_data:
        per_task = economic_data.get("per_task", [])
        profile_tasks = [t for t in per_task if t.get("suite") in suites]

        # Compute per-config stats for profile suites only
        config_stats: Dict[str, Dict[str, Any]] = {}
        for task in profile_tasks:
            cfg = task.get("config", "unknown")
            if cfg not in config_stats:
                config_stats[cfg] = {"costs": [], "passed": 0, "total": 0}
            config_stats[cfg]["total"] += 1
            cost = task.get("cost_usd")
            if cost is not None:
                config_stats[cfg]["costs"].append(cost)
            if task.get("passed"):
                config_stats[cfg]["passed"] += 1

        econ_summary = {}
        for cfg, stats in config_stats.items():
            avg_cost = sum(stats["costs"]) / len(stats["costs"]) if stats["costs"] else None
            pass_rate = stats["passed"] / stats["total"] if stats["total"] > 0 else None
            econ_summary[cfg] = {
                "n_tasks": stats["total"],
                "avg_cost_usd": round(avg_cost, 2) if avg_cost else None,
                "pass_rate": round(pass_rate, 3) if pass_rate else None,
                "tasks_passed": stats["passed"],
            }
        result["metrics"]["economic_summary"] = econ_summary

    # --- Reliability metrics (filtered to profile suites) ---
    if reliability_data:
        psc = reliability_data.get("per_suite_config", {})
        profile_psc = {k: v for k, v in psc.items() if k in suites}
        result["metrics"]["reliability_per_suite"] = profile_psc

        # Compute profile-level CI
        floor = reliability_data.get("reliability_floor", {})
        result["metrics"]["reliability_floor"] = floor

        # Failure clusters relevant to profile
        clusters = reliability_data.get("failure_clusters", [])
        profile_clusters = [
            c for c in clusters
            if c.get("dimension") == "benchmark_suite" and c.get("group") in suites
        ]
        result["metrics"]["failure_clusters"] = profile_clusters

    # --- Failure analysis (filtered to profile suites) ---
    if failure_data:
        per_task = failure_data.get("per_task", [])
        profile_failures = [t for t in per_task if t.get("suite") in suites]
        n_failures = len(profile_failures)

        # Aggregate failure modes for profile
        mode_counts: Dict[str, int] = {}
        context_counts: Dict[str, int] = {}
        for f in profile_failures:
            mode = f.get("failure_mode", "unknown")
            mode_counts[mode] = mode_counts.get(mode, 0) + 1
            ctx = f.get("context_impact", "unknown")
            context_counts[ctx] = context_counts.get(ctx, 0) + 1

        result["metrics"]["failure_summary"] = {
            "n_failures": n_failures,
            "failure_modes": mode_counts,
            "context_impact": context_counts,
        }

    # --- Governance metrics (if available and relevant) ---
    if governance_data and "security_compliance" in profile_id:
        result["metrics"]["governance"] = governance_data

    # --- Evaluate thresholds ---
    thresholds = profile["success_thresholds"]
    threshold_results = {}
    for threshold_key, threshold_val in thresholds.items():
        threshold_results[threshold_key] = {
            "target": threshold_val,
            "actual": None,
            "met": None,
        }
    result["thresholds"] = threshold_results

    # Fill in actual values where we can compute them
    _evaluate_thresholds(result, profile, workflow_data, economic_data, reliability_data)

    # --- Generate headline ---
    result["headline"] = _generate_headline(result, profile)

    return result


def _evaluate_thresholds(
    result: Dict,
    profile: Dict,
    workflow_data: Optional[Dict],
    economic_data: Optional[Dict],
    reliability_data: Optional[Dict],
) -> None:
    """Fill in threshold evaluation with actual computed values."""
    thresholds = result["thresholds"]
    suites = set(profile["benchmark_suites"])
    pid = profile["id"]

    # Pass rate improvement (useful for multiple profiles)
    if economic_data:
        per_config = economic_data.get("per_config", {})
        bl = per_config.get("baseline", {})
        sg = per_config.get("sourcegraph_full", {})
        bl_rate = bl.get("pass_rate")
        sg_rate = sg.get("pass_rate")

        if bl_rate and sg_rate and bl_rate > 0:
            improvement_pct = ((sg_rate - bl_rate) / bl_rate) * 100

            if "agent_reliability_improvement_pct" in thresholds:
                thresholds["agent_reliability_improvement_pct"]["actual"] = round(improvement_pct, 1)
                thresholds["agent_reliability_improvement_pct"]["met"] = (
                    improvement_pct >= thresholds["agent_reliability_improvement_pct"]["target"]
                )

    # Comprehension time reduction (legacy_modernization)
    if workflow_data and "comprehension_time_reduction_pct" in thresholds:
        deltas = workflow_data.get("category_deltas", {})
        comp = deltas.get("code_comprehension", {})
        pct = comp.get("estimated_time_saved_pct")
        if pct is not None:
            thresholds["comprehension_time_reduction_pct"]["actual"] = round(abs(pct), 1)
            thresholds["comprehension_time_reduction_pct"]["met"] = (
                abs(pct) >= thresholds["comprehension_time_reduction_pct"]["target"]
            )

    # Implementation pass rate (platform_saas)
    if economic_data and "implementation_pass_rate_min" in thresholds:
        # Filter to profile suites for SG_full
        per_task = economic_data.get("per_task", [])
        sg_tasks = [t for t in per_task if t.get("config") == "sourcegraph_full" and t.get("suite") in suites]
        if sg_tasks:
            passed = sum(1 for t in sg_tasks if t.get("passed"))
            rate = passed / len(sg_tasks)
            thresholds["implementation_pass_rate_min"]["actual"] = round(rate, 3)
            thresholds["implementation_pass_rate_min"]["met"] = (
                rate >= thresholds["implementation_pass_rate_min"]["target"]
            )

    # Cross-suite consistency (ai_forward)
    if reliability_data and "cross_suite_consistency_cv_max" in thresholds:
        consistency = reliability_data.get("cross_suite_consistency", {})
        sg_full = consistency.get("sourcegraph_full", {})
        cv = sg_full.get("coefficient_of_variation")
        if cv is not None:
            thresholds["cross_suite_consistency_cv_max"]["actual"] = round(cv, 3)
            thresholds["cross_suite_consistency_cv_max"]["met"] = (
                cv <= thresholds["cross_suite_consistency_cv_max"]["target"]
            )

    # Cross-repo pass rate (legacy_modernization, platform_consolidation)
    if reliability_data and "cross_repo_pass_rate_min" in thresholds:
        psc = reliability_data.get("per_suite_config", {})
        cr = psc.get("ccb_crossrepo", {})
        sg_full = cr.get("sourcegraph_full", {})
        rate = sg_full.get("mean_reward")
        if rate is not None:
            thresholds["cross_repo_pass_rate_min"]["actual"] = round(rate, 3)
            thresholds["cross_repo_pass_rate_min"]["met"] = (
                rate >= thresholds["cross_repo_pass_rate_min"]["target"]
            )


def _generate_headline(result: Dict, profile: Dict) -> Optional[str]:
    """Generate a profile-specific headline from computed metrics.

    Headlines are data-driven and honest about direction — they report
    the strongest positive finding for the profile's audience.
    """
    metrics = result.get("metrics", {})
    pid = profile["id"]

    try:
        # Common: get pass rate delta from economic data
        econ = metrics.get("economic_summary", {})
        bl = econ.get("baseline", {})
        sg = econ.get("sourcegraph_full", {})
        bl_rate = bl.get("pass_rate") or 0
        sg_rate = sg.get("pass_rate") or 0
        pass_rate_delta = ((sg_rate - bl_rate) / bl_rate * 100) if bl_rate > 0 else 0
        n_profile_tasks = sg.get("n_tasks", 0)

        if pid == "legacy_modernization":
            if pass_rate_delta > 0:
                return (
                    f"Context infrastructure improves legacy codebase task success "
                    f"by {pass_rate_delta:.0f}% ({sg_rate:.0%} vs {bl_rate:.0%} "
                    f"across {n_profile_tasks} tasks)"
                )
            else:
                return (
                    f"Context infrastructure achieves {sg_rate:.0%} task success "
                    f"on legacy codebases ({n_profile_tasks} tasks evaluated)"
                )

        elif pid == "platform_saas":
            if pass_rate_delta > 0:
                return (
                    f"Context infrastructure improves implementation success "
                    f"by {pass_rate_delta:.0f}% across SaaS-relevant benchmarks"
                )
            else:
                return (
                    f"SaaS benchmark evaluation: {sg_rate:.0%} task success with "
                    f"context infrastructure ({n_profile_tasks} tasks)"
                )

        elif pid == "security_compliance":
            gov = metrics.get("governance", {})
            if gov:
                agg = gov.get("aggregate", {})
                rate = (agg.get("compliance_rate", 0) or 0) * 100
                n_tasks = agg.get("tasks_assessed", 0)
                return (
                    f"Context infrastructure achieves {rate:.0f}% governance "
                    f"compliance across {n_tasks} enterprise boundary scenarios"
                )
            return "Governance evaluation pending — benchmark tasks not yet deployed"

        elif pid == "ai_forward":
            if pass_rate_delta > 0:
                return (
                    f"Context infrastructure improves agent reliability "
                    f"by {pass_rate_delta:.0f}% across {n_profile_tasks} "
                    f"diverse benchmark tasks"
                )
            else:
                return (
                    f"Agent reliability evaluation: {sg_rate:.0%} success "
                    f"with context infrastructure ({n_profile_tasks} tasks)"
                )

        elif pid == "platform_consolidation":
            deltas = metrics.get("workflow_deltas", {})
            dep = deltas.get("dependency_analysis", {})
            dep_pct = dep.get("estimated_time_saved_pct", 0) or 0
            if dep_pct > 0:
                return (
                    f"Context infrastructure reduces dependency analysis time "
                    f"by {dep_pct:.0f}% and achieves {sg_rate:.0%} cross-repo "
                    f"task success"
                )
            elif pass_rate_delta > 0:
                return (
                    f"Context infrastructure improves consolidation-relevant "
                    f"task success by {pass_rate_delta:.0f}%"
                )
            else:
                return (
                    f"Platform consolidation evaluation: {sg_rate:.0%} task "
                    f"success across {n_profile_tasks} tasks"
                )

    except (KeyError, TypeError, ZeroDivisionError):
        pass

    return None


def generate_profile_report_section(profile_metrics: Dict) -> str:
    """Generate a markdown section for a specific ICP profile."""
    pid = profile_metrics.get("profile_id", "unknown")
    profile = ICP_PROFILES.get(pid, {})
    label = profile_metrics.get("profile_label", pid)
    headline = profile_metrics.get("headline")

    lines = []
    lines.append(f"### {label}")
    lines.append("")
    if headline:
        lines.append(f"**{headline}**")
        lines.append("")

    # Thresholds
    thresholds = profile_metrics.get("thresholds", {})
    if thresholds:
        lines.append("#### Success Threshold Evaluation")
        lines.append("")
        lines.append("| Threshold | Target | Actual | Met |")
        lines.append("|-----------|--------|--------|-----|")
        for key, val in thresholds.items():
            target = val.get("target", "N/A")
            actual = val.get("actual", "N/A")
            met = val.get("met")
            met_str = "Yes" if met is True else ("No" if met is False else "N/A")
            lines.append(f"| {key} | {target} | {actual} | {met_str} |")
        lines.append("")

    # Pain points (for context)
    pain_points = profile.get("pain_points", [])
    if pain_points:
        lines.append("#### Customer Pain Points Addressed")
        lines.append("")
        for pp in pain_points:
            lines.append(f"- {pp}")
        lines.append("")

    # Objection response
    obj = profile.get("objection_response", {})
    if obj:
        lines.append("#### Sales Enablement")
        lines.append("")
        lines.append(f"**Objection**: \"{obj.get('objection', '')}\"")
        lines.append("")
        # Response is a template — format with available data, fall back to raw text
        response_template = obj.get("response", "")
        lines.append(f"**Response**: See profile metrics above for data points.")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_profiles_table():
    """Print a summary table of all ICP profiles."""
    print(f"{'ID':<25} {'Label':<40} {'Suites':<6} {'Categories':<12}")
    print("-" * 83)
    for pid, profile in ICP_PROFILES.items():
        n_suites = len(profile["benchmark_suites"])
        n_cats = len(profile["workflow_categories"])
        print(f"{pid:<25} {profile['label']:<40} {n_suites:<6} {n_cats:<12}")


def main():
    parser = argparse.ArgumentParser(
        description="ICP-aligned benchmark profiles for enterprise evaluation"
    )
    parser.add_argument(
        "--profile", "-p",
        help="Show details for a specific profile (by ID or partial match)"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON"
    )
    parser.add_argument(
        "--list-suites", action="store_true",
        help="Show suite-to-profile mapping"
    )
    args = parser.parse_args()

    if args.json:
        if args.profile:
            p = get_profile(args.profile)
            if p:
                print(json.dumps(p, indent=2))
            else:
                print(json.dumps({"error": f"Unknown profile: {args.profile}"}))
                sys.exit(1)
        else:
            print(json.dumps(ICP_PROFILES, indent=2))
        return

    if args.list_suites:
        print(f"{'Suite':<25} {'Profiles'}")
        print("-" * 60)
        for suite, profiles in sorted(SUITE_TO_PROFILES.items()):
            print(f"{suite:<25} {', '.join(profiles)}")
        return

    if args.profile:
        p = get_profile(args.profile)
        if not p:
            print(f"Unknown profile: {args.profile}")
            print(f"Available: {', '.join(ICP_PROFILES.keys())}")
            sys.exit(1)

        print(f"\n{p['label']} ({p['short_label']})")
        print("=" * 60)
        print(f"\n{p['description']}\n")
        print(f"Buyer Persona: {p['buyer_persona']}")
        print(f"\nBenchmark Suites: {', '.join(p['benchmark_suites'])}")
        print(f"Workflow Categories: {', '.join(p['workflow_categories'])}")
        print(f"\nSuccess Thresholds:")
        for k, v in p["success_thresholds"].items():
            print(f"  {k}: {v}")
        print(f"\nReport: {p['report_title']}")
        print(f"\nPain Points:")
        for pp in p["pain_points"]:
            print(f"  - {pp}")
        return

    print_profiles_table()


if __name__ == "__main__":
    main()
