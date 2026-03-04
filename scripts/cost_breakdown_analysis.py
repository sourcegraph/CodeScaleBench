#!/usr/bin/env python3
"""Cost breakdown analysis: investigate why SG_full costs ~4x more than baseline.

Walks all task_metrics.json files under runs/official/, groups by config,
and produces detailed token-type breakdowns, MCP correlation analysis,
per-suite comparisons, paired task analysis, and MCP overhead decomposition.

Usage:
    python3 scripts/cost_breakdown_analysis.py
"""

from __future__ import annotations

import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config_utils import is_config_dir, config_short_name

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs" / "official"
OUTPUT_JSON = Path(__file__).resolve().parent.parent / "docs" / "cost_breakdown.json"

SKIP_PATTERNS = [
    "__broken_verifier", "validation_test", "archive",
    "__archived", "preamble_test_", "__v1_hinted",
]

# Anthropic pricing (per million tokens) -- as specified in the analysis request
# Note: the actual cost_usd in task_metrics.json uses the Opus 4.5 pricing
# ($18.75/M cache_write, $1.50/M cache_read). These rates are from the request
# and used for the token-type decomposition analysis only.
PRICING_PER_MTOK = {
    "input": 15.0,
    "cache_create": 3.75,
    "cache_read": 0.30,
    "output": 75.0,
}

# Actual pricing used to compute cost_usd in task_metrics.json (Opus 4.5/4.6)
ACTUAL_PRICING_PER_MTOK = {
    "input": 15.0,
    "cache_create": 18.75,
    "cache_read": 1.50,
    "output": 75.0,
}

DIR_PREFIX_TO_SUITE = {
    # Legacy benchmark prefixes
    "bigcode_mcp_": "ccb_largerepo",
    "bigcode_sgcompare_": "ccb_largerepo",
    "codereview_": "ccb_codereview",
    "crossrepo_": "ccb_crossrepo",
    "dependeval_": "ccb_dependeval",
    "dibench_": "ccb_dibench",
    "docgen_": "ccb_docgen",
    "enterprise_": "ccb_enterprise",
    "governance_": "ccb_governance",
    "investigation_": "ccb_investigation",
    "k8s_docs_": "ccb_k8sdocs",
    "linuxflbench_": "ccb_linuxflbench",
    "locobench_": "ccb_locobench",
    "nlqa_": "ccb_nlqa",
    "onboarding_": "ccb_onboarding",
    "pytorch_": "ccb_pytorch",
    "repoqa_": "ccb_repoqa",
    "security_": "ccb_security",
    "swebenchpro_": "ccb_swebenchpro",
    "sweperf_": "ccb_sweperf",
    "tac_": "ccb_tac",
    "paired_rerun_dibench_": "ccb_dibench",
    "paired_rerun_crossrepo_": "ccb_crossrepo",
    "paired_rerun_pytorch_": "ccb_pytorch",
    "largerepo_": "ccb_largerepo",
    "paired_rerun_": None,
    # Legacy SDLC prefixes (ccb_{phase}_)
    "ccb_feature_": "csb_sdlc_feature",
    "ccb_refactor_": "csb_sdlc_refactor",
    "ccb_build_": "csb_sdlc_build",
    "ccb_debug_": "csb_sdlc_debug",
    "ccb_design_": "csb_sdlc_design",
    "ccb_document_": "csb_sdlc_document",
    "ccb_fix_": "csb_sdlc_fix",
    "ccb_secure_": "csb_sdlc_secure",
    "ccb_test_": "csb_sdlc_test",
    "ccb_understand_": "csb_sdlc_understand",
    # Legacy MCP-unique prefixes (ccb_mcp_{suite}_)
    "ccb_mcp_crossrepo_tracing_": "csb_org_crossrepo_tracing",
    "ccb_mcp_crossrepo_": "csb_org_crossrepo",
    "ccb_mcp_security_": "csb_org_security",
    "ccb_mcp_migration_": "csb_org_migration",
    "ccb_mcp_incident_": "csb_org_incident",
    "ccb_mcp_onboarding_": "csb_org_onboarding",
    "ccb_mcp_compliance_": "csb_org_compliance",
    "ccb_mcp_crossorg_": "csb_org_crossorg",
    "ccb_mcp_domain_": "csb_org_domain",
    "ccb_mcp_org_": "csb_org_org",
    "ccb_mcp_platform_": "csb_org_platform",
    # CodeScaleBench renamed suites (new canonical names)
    "csb_sdlc_feature_": "csb_sdlc_feature",
    "csb_sdlc_refactor_": "csb_sdlc_refactor",
    "csb_sdlc_build_": "csb_sdlc_build",
    "csb_sdlc_debug_": "csb_sdlc_debug",
    "csb_sdlc_design_": "csb_sdlc_design",
    "csb_sdlc_document_": "csb_sdlc_document",
    "csb_sdlc_fix_": "csb_sdlc_fix",
    "csb_sdlc_secure_": "csb_sdlc_secure",
    "csb_sdlc_test_": "csb_sdlc_test",
    "csb_sdlc_understand_": "csb_sdlc_understand",
    # CSB Org suites (must check crossrepo_tracing before crossrepo)
    "csb_org_crossrepo_tracing_": "csb_org_crossrepo_tracing",
    "csb_org_crossrepo_": "csb_org_crossrepo",
    "csb_org_security_": "csb_org_security",
    "csb_org_migration_": "csb_org_migration",
    "csb_org_incident_": "csb_org_incident",
    "csb_org_onboarding_": "csb_org_onboarding",
    "csb_org_compliance_": "csb_org_compliance",
    "csb_org_crossorg_": "csb_org_crossorg",
    "csb_org_domain_": "csb_org_domain",
    "csb_org_org_": "csb_org_org",
    "csb_org_platform_": "csb_org_platform",
    # Bare sdlc_ and org_ prefixes (short-form run names)
    "sdlc_feature_": "csb_sdlc_feature",
    "sdlc_refactor_": "csb_sdlc_refactor",
    "sdlc_build_": "csb_sdlc_build",
    "sdlc_debug_": "csb_sdlc_debug",
    "sdlc_design_": "csb_sdlc_design",
    "sdlc_document_": "csb_sdlc_document",
    "sdlc_fix_": "csb_sdlc_fix",
    "sdlc_secure_": "csb_sdlc_secure",
    "sdlc_test_": "csb_sdlc_test",
    "sdlc_understand_": "csb_sdlc_understand",
    "org_crossrepo_tracing_": "csb_org_crossrepo_tracing",
    "org_crossrepo_": "csb_org_crossrepo",
    "org_security_": "csb_org_security",
    "org_migration_": "csb_org_migration",
    "org_incident_": "csb_org_incident",
    "org_onboarding_": "csb_org_onboarding",
    "org_compliance_": "csb_org_compliance",
    "org_crossorg_": "csb_org_crossorg",
    "org_domain_": "csb_org_domain",
    "org_org_": "csb_org_org",
    "org_platform_": "csb_org_platform",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _infer_suite(task_id: str) -> str | None:
    """Infer suite from task_id patterns."""
    if task_id.startswith("instance_"):
        return "ccb_swebenchpro"
    if task_id.startswith("sgt-"):
        return "ccb_pytorch"
    if task_id.endswith("-doc-001"):
        return "ccb_k8sdocs"
    if task_id.startswith("big-code-"):
        return "ccb_largerepo"
    if task_id.startswith("dibench-"):
        return "ccb_dibench"
    if task_id.startswith("cr-"):
        return "ccb_codereview"
    if task_id.startswith("lfl-"):
        return "ccb_linuxflbench"
    if task_id.startswith("tac-"):
        return "ccb_tac"
    if task_id.startswith("repoqa-"):
        return "ccb_repoqa"
    if task_id.startswith("sweperf-"):
        return "ccb_sweperf"
    if task_id.startswith(("bug_localization_", "refactor_rename_", "cross_file_reasoning_", "simple_test_", "api_upgrade_")):
        return "ccb_crossrepo"
    if "_expert_" in task_id:
        return "ccb_locobench"
    if task_id.startswith(("multifile_editing-", "file_span_fix-", "dependency_recognition-")):
        return "ccb_dependeval"
    if any(task_id.startswith(p) for p in (
        "repo-scoped-", "sensitive-file-", "credential-",
        "multi-team-", "degraded-context-", "dep-",
        "polyglot-",
    )):
        return "ccb_enterprise"
    if any(task_id.startswith(p) for p in (
        "license-", "deprecated-api-", "security-vuln-",
        "code-quality-", "naming-convention-", "documentation-",
    )):
        return "ccb_governance"
    if task_id.startswith("inv-"):
        return "ccb_investigation"
    return None


def _is_zero_mcp_sg(record: dict) -> bool:
    """True if this is a sourcegraph_full run where MCP was never used.

    These runs are invalid treatment data — the MCP tools were available
    but the agent never invoked them, so the run is effectively a baseline
    with extra system-prompt overhead.
    """
    if record["config"] != "sourcegraph_full":
        return False
    mcp_calls = record.get("tool_calls_mcp")
    mcp_ratio = record.get("mcp_ratio")
    # Null tool_calls_mcp means extraction failed (H3 bug) — also flag these
    if mcp_calls is None or mcp_calls == 0:
        return True
    if mcp_ratio is not None and mcp_ratio == 0:
        return True
    return False


def _safe_mean(vals: list[float]) -> float:
    return statistics.mean(vals) if vals else 0.0


def _safe_median(vals: list[float]) -> float:
    return statistics.median(vals) if vals else 0.0


def _cost_from_tokens(input_tok: int, output_tok: int,
                      cache_create: int, cache_read: int,
                      pricing: dict = ACTUAL_PRICING_PER_MTOK) -> float:
    """Compute dollar cost from token counts using given pricing."""
    return (
        (input_tok / 1_000_000) * pricing["input"]
        + (output_tok / 1_000_000) * pricing["output"]
        + (cache_create / 1_000_000) * pricing["cache_create"]
        + (cache_read / 1_000_000) * pricing["cache_read"]
    )


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------

def collect_task_data() -> list[dict]:
    """Walk all task_metrics.json, dedup by (config, task_id) keeping latest."""
    all_tasks: dict[tuple[str, str], dict] = {}  # (config, task_id) -> record

    if not RUNS_DIR.exists():
        print(f"ERROR: {RUNS_DIR} does not exist", file=sys.stderr)
        return []

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir() or run_dir.name in ("archive", "MANIFEST.json"):
            continue
        if should_skip(run_dir.name):
            continue

        run_suite = _suite_from_run_dir(run_dir.name)

        for config_dir in sorted(run_dir.iterdir()):
            if not config_dir.is_dir():
                continue
            config_name = config_dir.name
            if not is_config_dir(config_name):
                continue

            for batch_dir in sorted(config_dir.iterdir()):
                if not batch_dir.is_dir() or not _is_batch_timestamp(batch_dir.name):
                    continue
                if should_skip(batch_dir.name):
                    continue

                for task_dir in sorted(batch_dir.iterdir()):
                    if not task_dir.is_dir():
                        continue
                    if should_skip(task_dir.name):
                        continue

                    metrics_file = task_dir / "task_metrics.json"
                    if not metrics_file.is_file():
                        continue

                    try:
                        m = json.loads(metrics_file.read_text())
                    except (json.JSONDecodeError, OSError):
                        continue

                    task_id = m.get("task_id", "")
                    if not task_id:
                        continue

                    # Skip zero-token runs (auth failures, etc.)
                    cost_usd = m.get("cost_usd") or 0
                    input_tokens = m.get("input_tokens") or 0
                    output_tokens = m.get("output_tokens") or 0
                    cache_create = m.get("cache_creation_tokens") or 0
                    cache_read = m.get("cache_read_tokens") or 0

                    if (input_tokens + output_tokens + cache_create + cache_read) == 0:
                        continue

                    # Timestamp-based dedup
                    started_at = ""
                    result_file = task_dir / "result.json"
                    if result_file.is_file():
                        try:
                            rdata = json.loads(result_file.read_text())
                            started_at = rdata.get("started_at", "")
                        except (json.JSONDecodeError, OSError):
                            pass

                    suite = run_suite
                    if suite is None:
                        suite = _infer_suite(task_id) or m.get("benchmark", "unknown")

                    record = {
                        "task_id": task_id,
                        "config": config_name,
                        "suite": suite,
                        "cost_usd": float(cost_usd),
                        "input_tokens": int(input_tokens),
                        "output_tokens": int(output_tokens),
                        "cache_creation_tokens": int(cache_create),
                        "cache_read_tokens": int(cache_read),
                        "mcp_ratio": m.get("mcp_ratio"),
                        "tool_calls_mcp": m.get("tool_calls_mcp"),
                        "tool_calls_local": m.get("tool_calls_local"),
                        "mcp_latency_p50_ms": m.get("mcp_latency_p50_ms"),
                        "mcp_latency_p95_ms": m.get("mcp_latency_p95_ms"),
                        "agent_execution_seconds": m.get("agent_execution_seconds"),
                        "wall_clock_seconds": m.get("wall_clock_seconds"),
                        "reward": m.get("reward"),
                        "status": m.get("status"),
                        "conversation_turns": m.get("conversation_turns"),
                        "tool_calls_total": m.get("tool_calls_total"),
                        "started_at": started_at,
                        "task_dir": str(task_dir),
                    }

                    key = (config_name, task_id)
                    if key in all_tasks:
                        if started_at > all_tasks[key].get("started_at", ""):
                            all_tasks[key] = record
                    else:
                        all_tasks[key] = record

    return list(all_tasks.values())


# ---------------------------------------------------------------------------
# Analysis A: Token type breakdown per config
# ---------------------------------------------------------------------------

def analysis_a_token_breakdown(data: list[dict]) -> dict:
    """Token type breakdown per config with dollar cost contribution."""
    by_config: dict[str, list[dict]] = defaultdict(list)
    for r in data:
        by_config[r["config"]].append(r)

    result = {}
    for config in sorted(by_config.keys()):
        recs = by_config[config]
        if not recs:
            continue

        n = len(recs)
        mean_input = _safe_mean([r["input_tokens"] for r in recs])
        mean_output = _safe_mean([r["output_tokens"] for r in recs])
        mean_cache_create = _safe_mean([r["cache_creation_tokens"] for r in recs])
        mean_cache_read = _safe_mean([r["cache_read_tokens"] for r in recs])

        # Dollar cost per token type (using actual pricing)
        cost_input = mean_input / 1_000_000 * ACTUAL_PRICING_PER_MTOK["input"]
        cost_output = mean_output / 1_000_000 * ACTUAL_PRICING_PER_MTOK["output"]
        cost_cache_create = mean_cache_create / 1_000_000 * ACTUAL_PRICING_PER_MTOK["cache_create"]
        cost_cache_read = mean_cache_read / 1_000_000 * ACTUAL_PRICING_PER_MTOK["cache_read"]
        total_cost = cost_input + cost_output + cost_cache_create + cost_cache_read

        result[config] = {
            "n_tasks": n,
            "mean_cost_usd": round(_safe_mean([r["cost_usd"] for r in recs]), 4),
            "median_cost_usd": round(_safe_median([r["cost_usd"] for r in recs]), 4),
            "mean_input_tokens": round(mean_input),
            "mean_output_tokens": round(mean_output),
            "mean_cache_creation_tokens": round(mean_cache_create),
            "mean_cache_read_tokens": round(mean_cache_read),
            "dollar_input": round(cost_input, 4),
            "dollar_output": round(cost_output, 4),
            "dollar_cache_create": round(cost_cache_create, 4),
            "dollar_cache_read": round(cost_cache_read, 4),
            "dollar_total_computed": round(total_cost, 4),
            "pct_input": round(cost_input / total_cost * 100, 1) if total_cost > 0 else 0,
            "pct_output": round(cost_output / total_cost * 100, 1) if total_cost > 0 else 0,
            "pct_cache_create": round(cost_cache_create / total_cost * 100, 1) if total_cost > 0 else 0,
            "pct_cache_read": round(cost_cache_read / total_cost * 100, 1) if total_cost > 0 else 0,
        }

    # Compute delta drivers
    bl = result.get("baseline", {})
    sg = result.get("sourcegraph_full", {})
    if bl and sg:
        delta_input = sg.get("dollar_input", 0) - bl.get("dollar_input", 0)
        delta_output = sg.get("dollar_output", 0) - bl.get("dollar_output", 0)
        delta_cache_create = sg.get("dollar_cache_create", 0) - bl.get("dollar_cache_create", 0)
        delta_cache_read = sg.get("dollar_cache_read", 0) - bl.get("dollar_cache_read", 0)
        total_delta = delta_input + delta_output + delta_cache_create + delta_cache_read

        result["cost_delta_drivers"] = {
            "total_delta": round(total_delta, 4),
            "delta_input": round(delta_input, 4),
            "delta_output": round(delta_output, 4),
            "delta_cache_create": round(delta_cache_create, 4),
            "delta_cache_read": round(delta_cache_read, 4),
            "pct_from_input": round(delta_input / total_delta * 100, 1) if total_delta != 0 else 0,
            "pct_from_output": round(delta_output / total_delta * 100, 1) if total_delta != 0 else 0,
            "pct_from_cache_create": round(delta_cache_create / total_delta * 100, 1) if total_delta != 0 else 0,
            "pct_from_cache_read": round(delta_cache_read / total_delta * 100, 1) if total_delta != 0 else 0,
        }

    return result


# ---------------------------------------------------------------------------
# Analysis B: Cost vs MCP ratio correlation
# ---------------------------------------------------------------------------

def analysis_b_cost_mcp_correlation(data: list[dict]) -> dict:
    """For SG_full tasks, bucket by mcp_ratio and show cost patterns."""
    sg_data = [r for r in data if r["config"] == "sourcegraph_full" and r.get("mcp_ratio") is not None]

    buckets = {
        "0%": [],
        "1-10%": [],
        "11-25%": [],
        "26-50%": [],
        "51%+": [],
    }

    for r in sg_data:
        ratio = r["mcp_ratio"]
        if ratio == 0:
            buckets["0%"].append(r)
        elif ratio <= 0.10:
            buckets["1-10%"].append(r)
        elif ratio <= 0.25:
            buckets["11-25%"].append(r)
        elif ratio <= 0.50:
            buckets["26-50%"].append(r)
        else:
            buckets["51%+"].append(r)

    result = {}
    for bucket_name, recs in buckets.items():
        if not recs:
            result[bucket_name] = {"n": 0}
            continue
        result[bucket_name] = {
            "n": len(recs),
            "mean_cost_usd": round(_safe_mean([r["cost_usd"] for r in recs]), 4),
            "median_cost_usd": round(_safe_median([r["cost_usd"] for r in recs]), 4),
            "mean_tool_calls_mcp": round(_safe_mean([r["tool_calls_mcp"] for r in recs if r.get("tool_calls_mcp") is not None]), 1),
            "mean_tool_calls_local": round(_safe_mean([r["tool_calls_local"] for r in recs if r.get("tool_calls_local") is not None]), 1),
            "mean_mcp_ratio": round(_safe_mean([r["mcp_ratio"] for r in recs]), 3),
            "mean_output_tokens": round(_safe_mean([r["output_tokens"] for r in recs])),
            "mean_cache_read_tokens": round(_safe_mean([r["cache_read_tokens"] for r in recs])),
            "mean_conversation_turns": round(_safe_mean([r["conversation_turns"] for r in recs if r.get("conversation_turns")]), 1),
        }

    return result


# ---------------------------------------------------------------------------
# Analysis C: Per-suite cost breakdown
# ---------------------------------------------------------------------------

def analysis_c_suite_breakdown(data: list[dict]) -> dict:
    """Per-suite cost breakdown with deltas."""
    by_suite_config: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in data:
        by_suite_config[(r["suite"], r["config"])].append(r)

    # Build per-suite-config table
    suite_table = {}
    for (suite, config), recs in sorted(by_suite_config.items()):
        key = f"{suite}__{config}"
        suite_table[key] = {
            "n": len(recs),
            "mean_cost_usd": round(_safe_mean([r["cost_usd"] for r in recs]), 4),
            "median_cost_usd": round(_safe_median([r["cost_usd"] for r in recs]), 4),
            "total_cost_usd": round(sum(r["cost_usd"] for r in recs), 2),
            "mean_output_tokens": round(_safe_mean([r["output_tokens"] for r in recs])),
            "mean_cache_read_tokens": round(_safe_mean([r["cache_read_tokens"] for r in recs])),
        }

    # Compute deltas per suite
    suites = set(r["suite"] for r in data)
    deltas = {}
    for suite in sorted(suites):
        bl_recs = by_suite_config.get((suite, "baseline"), [])
        sg_recs = by_suite_config.get((suite, "sourcegraph_full"), [])
        if not bl_recs or not sg_recs:
            continue
        bl_mean = _safe_mean([r["cost_usd"] for r in bl_recs])
        sg_mean = _safe_mean([r["cost_usd"] for r in sg_recs])
        delta = sg_mean - bl_mean
        pct = (delta / bl_mean * 100) if bl_mean > 0 else 0
        deltas[suite] = {
            "n_baseline": len(bl_recs),
            "n_sg_full": len(sg_recs),
            "mean_cost_bl": round(bl_mean, 4),
            "mean_cost_sg": round(sg_mean, 4),
            "delta": round(delta, 4),
            "pct_change": round(pct, 1),
            "total_delta_contribution": round(delta * min(len(bl_recs), len(sg_recs)), 2),
        }

    return {"per_suite_config": suite_table, "deltas": deltas}


# ---------------------------------------------------------------------------
# Analysis D: Paired task analysis
# ---------------------------------------------------------------------------

def analysis_d_paired_tasks(data: list[dict]) -> dict:
    """For tasks with BOTH configs, show cost breakdown and delta attribution."""
    by_task: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in data:
        by_task[r["task_id"]][r["config"]] = r

    paired = []
    for task_id, configs in sorted(by_task.items()):
        if "baseline" not in configs or "sourcegraph_full" not in configs:
            continue

        bl = configs["baseline"]
        sg = configs["sourcegraph_full"]

        delta_cost = sg["cost_usd"] - bl["cost_usd"]
        delta_input = (sg["input_tokens"] - bl["input_tokens"]) / 1_000_000 * ACTUAL_PRICING_PER_MTOK["input"]
        delta_output = (sg["output_tokens"] - bl["output_tokens"]) / 1_000_000 * ACTUAL_PRICING_PER_MTOK["output"]
        delta_cache_create = (sg["cache_creation_tokens"] - bl["cache_creation_tokens"]) / 1_000_000 * ACTUAL_PRICING_PER_MTOK["cache_create"]
        delta_cache_read = (sg["cache_read_tokens"] - bl["cache_read_tokens"]) / 1_000_000 * ACTUAL_PRICING_PER_MTOK["cache_read"]

        total_computed_delta = delta_input + delta_output + delta_cache_create + delta_cache_read

        paired.append({
            "task_id": task_id,
            "suite": bl.get("suite", sg.get("suite", "unknown")),
            "cost_usd_bl": round(bl["cost_usd"], 4),
            "cost_usd_sg": round(sg["cost_usd"], 4),
            "delta": round(delta_cost, 4),
            "pct_change": round((delta_cost / bl["cost_usd"] * 100) if bl["cost_usd"] > 0 else 0, 1),
            "output_tokens_bl": bl["output_tokens"],
            "output_tokens_sg": sg["output_tokens"],
            "cache_read_bl": bl["cache_read_tokens"],
            "cache_read_sg": sg["cache_read_tokens"],
            "cache_create_bl": bl["cache_creation_tokens"],
            "cache_create_sg": sg["cache_creation_tokens"],
            "delta_from_input": round(delta_input, 4),
            "delta_from_output": round(delta_output, 4),
            "delta_from_cache_create": round(delta_cache_create, 4),
            "delta_from_cache_read": round(delta_cache_read, 4),
            "mcp_ratio": sg.get("mcp_ratio"),
            "turns_bl": bl.get("conversation_turns"),
            "turns_sg": sg.get("conversation_turns"),
        })

    # Summary: what fraction of total cost delta comes from each token type
    if paired:
        total_delta_from_input = sum(p["delta_from_input"] for p in paired)
        total_delta_from_output = sum(p["delta_from_output"] for p in paired)
        total_delta_from_cache_create = sum(p["delta_from_cache_create"] for p in paired)
        total_delta_from_cache_read = sum(p["delta_from_cache_read"] for p in paired)
        total_delta = total_delta_from_input + total_delta_from_output + total_delta_from_cache_create + total_delta_from_cache_read

        n_more_expensive = sum(1 for p in paired if p["delta"] > 0)
        n_cheaper = sum(1 for p in paired if p["delta"] < 0)
        n_same = sum(1 for p in paired if p["delta"] == 0)

        summary = {
            "n_paired": len(paired),
            "n_sg_more_expensive": n_more_expensive,
            "n_sg_cheaper": n_cheaper,
            "n_same_cost": n_same,
            "mean_delta_usd": round(_safe_mean([p["delta"] for p in paired]), 4),
            "median_delta_usd": round(_safe_median([p["delta"] for p in paired]), 4),
            "total_delta_usd": round(total_delta, 2),
            "fraction_from_input": round(total_delta_from_input / total_delta * 100, 1) if total_delta != 0 else 0,
            "fraction_from_output": round(total_delta_from_output / total_delta * 100, 1) if total_delta != 0 else 0,
            "fraction_from_cache_create": round(total_delta_from_cache_create / total_delta * 100, 1) if total_delta != 0 else 0,
            "fraction_from_cache_read": round(total_delta_from_cache_read / total_delta * 100, 1) if total_delta != 0 else 0,
        }
    else:
        summary = {"n_paired": 0}

    # Sort by absolute delta descending
    paired.sort(key=lambda p: abs(p["delta"]), reverse=True)

    return {"summary": summary, "tasks": paired}


# ---------------------------------------------------------------------------
# Analysis E: MCP overhead decomposition
# ---------------------------------------------------------------------------

def analysis_e_mcp_overhead(data: list[dict]) -> dict:
    """Decompose MCP overhead: how does MCP usage affect tokens and cost."""
    by_task: dict[str, dict[str, dict]] = defaultdict(dict)
    for r in data:
        by_task[r["task_id"]][r["config"]] = r

    # Matched pairs where SG_full has mcp_ratio > 0
    mcp_active = []
    mcp_zero = []

    for task_id, configs in sorted(by_task.items()):
        if "baseline" not in configs or "sourcegraph_full" not in configs:
            continue
        bl = configs["baseline"]
        sg = configs["sourcegraph_full"]
        mcp_ratio = sg.get("mcp_ratio")
        if mcp_ratio is None:
            continue

        entry = {
            "task_id": task_id,
            "suite": bl.get("suite", "unknown"),
            "mcp_ratio": mcp_ratio,
            "cost_bl": bl["cost_usd"],
            "cost_sg": sg["cost_usd"],
            "output_bl": bl["output_tokens"],
            "output_sg": sg["output_tokens"],
            "cache_read_bl": bl["cache_read_tokens"],
            "cache_read_sg": sg["cache_read_tokens"],
            "cache_create_bl": bl["cache_creation_tokens"],
            "cache_create_sg": sg["cache_creation_tokens"],
            "turns_bl": bl.get("conversation_turns"),
            "turns_sg": sg.get("conversation_turns"),
            "mcp_latency_p50": sg.get("mcp_latency_p50_ms"),
            "mcp_latency_p95": sg.get("mcp_latency_p95_ms"),
            "tool_calls_mcp": sg.get("tool_calls_mcp") or 0,
            "tool_calls_local_sg": sg.get("tool_calls_local") or 0,
            "tool_calls_local_bl": bl.get("tool_calls_local") or 0,
        }

        if mcp_ratio > 0:
            mcp_active.append(entry)
        else:
            mcp_zero.append(entry)

    def _summarize(entries: list[dict]) -> dict:
        if not entries:
            return {"n": 0}
        return {
            "n": len(entries),
            "mean_cost_delta": round(_safe_mean([e["cost_sg"] - e["cost_bl"] for e in entries]), 4),
            "mean_cost_bl": round(_safe_mean([e["cost_bl"] for e in entries]), 4),
            "mean_cost_sg": round(_safe_mean([e["cost_sg"] for e in entries]), 4),
            "mean_output_delta": round(_safe_mean([e["output_sg"] - e["output_bl"] for e in entries])),
            "mean_output_bl": round(_safe_mean([e["output_bl"] for e in entries])),
            "mean_output_sg": round(_safe_mean([e["output_sg"] for e in entries])),
            "mean_cache_read_delta": round(_safe_mean([e["cache_read_sg"] - e["cache_read_bl"] for e in entries])),
            "mean_cache_read_bl": round(_safe_mean([e["cache_read_bl"] for e in entries])),
            "mean_cache_read_sg": round(_safe_mean([e["cache_read_sg"] for e in entries])),
            "mean_cache_create_delta": round(_safe_mean([e["cache_create_sg"] - e["cache_create_bl"] for e in entries])),
            "mean_turns_bl": round(_safe_mean([e["turns_bl"] for e in entries if e.get("turns_bl")]), 1),
            "mean_turns_sg": round(_safe_mean([e["turns_sg"] for e in entries if e.get("turns_sg")]), 1),
            "mean_mcp_calls": round(_safe_mean([e["tool_calls_mcp"] for e in entries]), 1),
            "mean_mcp_ratio": round(_safe_mean([e["mcp_ratio"] for e in entries]), 3),
            "mean_mcp_latency_p50": round(_safe_mean([e["mcp_latency_p50"] for e in entries if e.get("mcp_latency_p50") is not None]), 0),
            "mean_mcp_latency_p95": round(_safe_mean([e["mcp_latency_p95"] for e in entries if e.get("mcp_latency_p95") is not None]), 0),
        }

    # Correlation: output token increase vs MCP ratio for active pairs
    correlation_note = ""
    if len(mcp_active) >= 3:
        output_deltas = [e["output_sg"] - e["output_bl"] for e in mcp_active]
        mcp_ratios = [e["mcp_ratio"] for e in mcp_active]
        # Simple Pearson correlation
        n = len(output_deltas)
        mean_x = sum(mcp_ratios) / n
        mean_y = sum(output_deltas) / n
        cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(mcp_ratios, output_deltas)) / n
        std_x = (sum((x - mean_x) ** 2 for x in mcp_ratios) / n) ** 0.5
        std_y = (sum((y - mean_y) ** 2 for y in output_deltas) / n) ** 0.5
        if std_x > 0 and std_y > 0:
            pearson_r = cov / (std_x * std_y)
            correlation_note = f"Pearson r(mcp_ratio, output_token_delta) = {pearson_r:.3f} (n={n})"
        else:
            correlation_note = "Insufficient variance for correlation"

    return {
        "mcp_active_pairs": _summarize(mcp_active),
        "mcp_zero_pairs": _summarize(mcp_zero),
        "correlation": correlation_note,
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def print_analysis_a(result: dict) -> None:
    print("=" * 90)
    print("ANALYSIS A: Token Type Breakdown Per Config")
    print("=" * 90)
    print(f"\n  NOTE: Dollar costs computed using Anthropic Opus 4.5/4.6 pricing:")
    print(f"    input=${ACTUAL_PRICING_PER_MTOK['input']}/Mtok, output=${ACTUAL_PRICING_PER_MTOK['output']}/Mtok,")
    print(f"    cache_write=${ACTUAL_PRICING_PER_MTOK['cache_create']}/Mtok, cache_read=${ACTUAL_PRICING_PER_MTOK['cache_read']}/Mtok\n")

    header = (
        f"  {'Config':20s} {'n':>5s} {'MeanCost':>10s} {'MedCost':>10s} "
        f"{'Input':>12s} {'Output':>12s} {'CacheWrite':>12s} {'CacheRead':>14s}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))

    for config in sorted(result.keys()):
        c = result.get(config)
        if not c or not isinstance(c, dict) or "n_tasks" not in c:
            continue
        short = config_short_name(config)
        print(
            f"  {short:20s} {c['n_tasks']:>5d} ${c['mean_cost_usd']:>8.4f} ${c['median_cost_usd']:>8.4f} "
            f"{c['mean_input_tokens']:>12,} {c['mean_output_tokens']:>12,} "
            f"{c['mean_cache_creation_tokens']:>12,} {c['mean_cache_read_tokens']:>14,}"
        )

    print("\n  Dollar cost contribution by token type (mean per task):")
    header2 = f"  {'Config':20s} {'$Input':>10s} {'$Output':>10s} {'$CacheWr':>10s} {'$CacheRd':>10s} {'$Total':>10s}"
    print(header2)
    print("  " + "-" * (len(header2) - 2))

    for config in sorted(result.keys()):
        c = result.get(config)
        if not c or not isinstance(c, dict) or "dollar_input" not in c:
            continue
        short = config_short_name(config)
        print(
            f"  {short:20s} ${c['dollar_input']:>8.4f} ${c['dollar_output']:>8.4f} "
            f"${c['dollar_cache_create']:>8.4f} ${c['dollar_cache_read']:>8.4f} "
            f"${c['dollar_total_computed']:>8.4f}"
        )

    print("\n  Percentage of cost by token type:")
    header3 = f"  {'Config':20s} {'%Input':>8s} {'%Output':>8s} {'%CacheWr':>8s} {'%CacheRd':>8s}"
    print(header3)
    print("  " + "-" * (len(header3) - 2))

    for config in sorted(result.keys()):
        c = result.get(config)
        if not c or not isinstance(c, dict) or "pct_input" not in c:
            continue
        short = config_short_name(config)
        print(
            f"  {short:20s} {c['pct_input']:>7.1f}% {c['pct_output']:>7.1f}% "
            f"{c['pct_cache_create']:>7.1f}% {c['pct_cache_read']:>7.1f}%"
        )

    drivers = result.get("cost_delta_drivers")
    if drivers:
        print(f"\n  COST DELTA DRIVERS (SG_full - baseline per task):")
        print(f"    Total delta:      ${drivers['total_delta']:>+10.4f}")
        print(f"    From input:       ${drivers['delta_input']:>+10.4f}  ({drivers['pct_from_input']:>+.1f}% of delta)")
        print(f"    From output:      ${drivers['delta_output']:>+10.4f}  ({drivers['pct_from_output']:>+.1f}% of delta)")
        print(f"    From cache_write: ${drivers['delta_cache_create']:>+10.4f}  ({drivers['pct_from_cache_create']:>+.1f}% of delta)")
        print(f"    From cache_read:  ${drivers['delta_cache_read']:>+10.4f}  ({drivers['pct_from_cache_read']:>+.1f}% of delta)")
    print()


def print_analysis_b(result: dict) -> None:
    print("=" * 90)
    print("ANALYSIS B: Cost vs MCP Ratio Correlation (SG_full tasks)")
    print("=" * 90)

    header = (
        f"  {'Bucket':>10s} {'n':>5s} {'MeanCost':>10s} {'MedCost':>10s} "
        f"{'MCPCalls':>8s} {'LocalCalls':>10s} {'MeanRatio':>10s} {'MeanOut':>12s} {'Turns':>6s}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))

    for bucket in ["0%", "1-10%", "11-25%", "26-50%", "51%+"]:
        b = result.get(bucket, {})
        n = b.get("n", 0)
        if n == 0:
            print(f"  {bucket:>10s} {0:>5d}   {'(no data)':>50s}")
            continue
        print(
            f"  {bucket:>10s} {n:>5d} ${b['mean_cost_usd']:>8.4f} ${b['median_cost_usd']:>8.4f} "
            f"{b['mean_tool_calls_mcp']:>8.1f} {b['mean_tool_calls_local']:>10.1f} "
            f"{b['mean_mcp_ratio']:>10.3f} {b['mean_output_tokens']:>12,} {b['mean_conversation_turns']:>6.1f}"
        )
    print()


def print_analysis_c(result: dict) -> None:
    print("=" * 90)
    print("ANALYSIS C: Per-Suite Cost Breakdown")
    print("=" * 90)

    deltas = result.get("deltas", {})
    if deltas:
        header = (
            f"  {'Suite':25s} {'nBL':>4s} {'nSG':>4s} {'MeanBL':>10s} {'MeanSG':>10s} "
            f"{'Delta':>10s} {'%Chg':>8s} {'TotalDelta':>12s}"
        )
        print(header)
        print("  " + "-" * (len(header) - 2))

        # Sort by absolute delta descending
        for suite, d in sorted(deltas.items(), key=lambda x: abs(x[1]["delta"]), reverse=True):
            print(
                f"  {suite:25s} {d['n_baseline']:>4d} {d['n_sg_full']:>4d} "
                f"${d['mean_cost_bl']:>8.4f} ${d['mean_cost_sg']:>8.4f} "
                f"${d['delta']:>+8.4f} {d['pct_change']:>+7.1f}% "
                f"${d['total_delta_contribution']:>+10.2f}"
            )
    print()


def print_analysis_d(result: dict) -> None:
    print("=" * 90)
    print("ANALYSIS D: Paired Task Analysis")
    print("=" * 90)

    s = result.get("summary", {})
    if s.get("n_paired", 0) == 0:
        print("  No paired tasks found.")
        return

    print(f"\n  Paired tasks:       {s['n_paired']}")
    print(f"  SG more expensive:  {s['n_sg_more_expensive']}")
    print(f"  SG cheaper:         {s['n_sg_cheaper']}")
    print(f"  Same cost:          {s['n_same_cost']}")
    print(f"  Mean delta:         ${s['mean_delta_usd']:+.4f}")
    print(f"  Median delta:       ${s['median_delta_usd']:+.4f}")

    print(f"\n  COST DELTA ATTRIBUTION (across all paired tasks):")
    print(f"    Total delta:            ${s['total_delta_usd']:>+.2f}")
    print(f"    From input tokens:      {s['fraction_from_input']:>+.1f}%")
    print(f"    From output tokens:     {s['fraction_from_output']:>+.1f}%")
    print(f"    From cache_write:       {s['fraction_from_cache_create']:>+.1f}%")
    print(f"    From cache_read:        {s['fraction_from_cache_read']:>+.1f}%")

    # Show top 15 most-delta tasks
    tasks = result.get("tasks", [])
    if tasks:
        print(f"\n  Top 15 tasks by absolute cost delta:")
        header = (
            f"    {'Task':55s} {'Suite':20s} {'CostBL':>8s} {'CostSG':>8s} "
            f"{'Delta':>10s} {'%Chg':>8s} {'MCP%':>6s}"
        )
        print(header)
        print("    " + "-" * (len(header) - 4))
        for p in tasks[:15]:
            mcp_str = f"{p['mcp_ratio']:.2f}" if p.get("mcp_ratio") is not None else "N/A"
            tid = p["task_id"][:55]
            print(
                f"    {tid:55s} {p['suite']:20s} ${p['cost_usd_bl']:>6.2f} ${p['cost_usd_sg']:>6.2f} "
                f"${p['delta']:>+8.2f} {p['pct_change']:>+7.1f}% {mcp_str:>6s}"
            )
    print()


def print_outlier_analysis(data: list[dict]) -> None:
    """Identify and report cost outliers that skew aggregate numbers."""
    print("=" * 90)
    print("OUTLIER ANALYSIS: Tasks with extreme cost values")
    print("=" * 90)

    # Identify tasks > $50 (extreme outliers)
    outliers = [r for r in data if r["cost_usd"] > 50]
    outliers.sort(key=lambda r: r["cost_usd"], reverse=True)

    if not outliers:
        print("  No extreme outliers (>$50) found.")
    else:
        print(f"\n  Tasks costing >$50 ({len(outliers)} found):")
        for r in outliers:
            cache_read = r["cache_read_tokens"]
            cache_note = "  [NO CACHE READS -- likely broken prompt caching]" if cache_read == 0 else ""
            print(
                f"    ${r['cost_usd']:>8.2f}  {r['config']:20s}  {r['task_id'][:50]}"
                f"  input={r['input_tokens']:>12,}  cache_w={r['cache_creation_tokens']:>12,}"
                f"  cache_r={cache_read:>12,}{cache_note}"
            )

    # Show aggregate impact of outliers
    by_config: dict[str, list[dict]] = defaultdict(list)
    for r in data:
        by_config[r["config"]].append(r)

    print(f"\n  Impact of >$50 outlier removal:")
    header = f"    {'Config':20s} {'MeanWith':>10s} {'MeanWithout':>12s} {'Delta':>10s}"
    print(header)
    print("    " + "-" * (len(header) - 4))
    for config in sorted(by_config.keys()):
        recs = by_config.get(config, [])
        if not recs:
            continue
        filtered = [r for r in recs if r["cost_usd"] <= 50]
        mean_all = _safe_mean([r["cost_usd"] for r in recs])
        mean_filtered = _safe_mean([r["cost_usd"] for r in filtered])
        n_removed = len(recs) - len(filtered)
        short = config_short_name(config)
        print(
            f"    {short:20s} ${mean_all:>8.4f} ${mean_filtered:>10.4f} "
            f"${mean_all - mean_filtered:>+8.4f}  (removed {n_removed} tasks)"
        )
    print()


def print_analysis_e(result: dict) -> None:
    print("=" * 90)
    print("ANALYSIS E: MCP Overhead Decomposition")
    print("=" * 90)

    for label, key in [("MCP ACTIVE (mcp_ratio > 0)", "mcp_active_pairs"),
                       ("MCP ZERO (mcp_ratio = 0)", "mcp_zero_pairs")]:
        s = result.get(key, {})
        n = s.get("n", 0)
        print(f"\n  {label}: {n} paired tasks")
        if n == 0:
            continue

        print(f"    Mean cost delta (SG - BL):     ${s['mean_cost_delta']:>+.4f}")
        print(f"    Mean cost BL / SG:             ${s['mean_cost_bl']:.4f} / ${s['mean_cost_sg']:.4f}")
        print(f"    Mean output delta:             {s['mean_output_delta']:>+,} tokens")
        print(f"    Mean output BL / SG:           {s['mean_output_bl']:>12,} / {s['mean_output_sg']:>12,}")
        print(f"    Mean cache_read delta:         {s['mean_cache_read_delta']:>+,} tokens")
        print(f"    Mean cache_read BL / SG:       {s['mean_cache_read_bl']:>12,} / {s['mean_cache_read_sg']:>12,}")
        print(f"    Mean cache_create delta:       {s['mean_cache_create_delta']:>+,} tokens")
        print(f"    Mean turns BL / SG:            {s['mean_turns_bl']:.1f} / {s['mean_turns_sg']:.1f}")
        if s.get("mean_mcp_calls"):
            print(f"    Mean MCP calls:                {s['mean_mcp_calls']:.1f}")
            print(f"    Mean MCP ratio:                {s['mean_mcp_ratio']:.3f}")
        if s.get("mean_mcp_latency_p50"):
            print(f"    Mean MCP latency p50/p95:      {s['mean_mcp_latency_p50']:.0f}ms / {s['mean_mcp_latency_p95']:.0f}ms")

    corr = result.get("correlation", "")
    if corr:
        print(f"\n  Correlation: {corr}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def print_flagged_runs(flagged: list[dict]) -> None:
    """Report zero-MCP SG_full runs that were excluded from analysis."""
    print("=" * 90)
    print("FLAGGED INVALID: SG_full runs with ZERO MCP tool usage")
    print("=" * 90)
    print(f"\n  {len(flagged)} SG_full runs excluded (MCP tools available but never invoked).")
    print("  These are invalid treatment data — effectively baselines with extra prompt overhead.\n")

    # Group by suite
    by_suite: dict[str, list[dict]] = defaultdict(list)
    for r in flagged:
        by_suite[r["suite"]].append(r)

    header = f"    {'Task':50s} {'Suite':22s} {'Cost':>8s} {'Reward':>8s} {'Calls':>6s} {'Reason':>12s}"
    print(header)
    print("    " + "-" * (len(header) - 4))

    for suite in sorted(by_suite):
        for r in sorted(by_suite[suite], key=lambda x: x["task_id"]):
            calls = r.get("tool_calls_total")
            calls_str = str(calls) if calls is not None else "N/A"
            reward = r.get("reward")
            reward_str = f"{reward:.3f}" if reward is not None else "N/A"
            cost_str = f"${r['cost_usd']:.2f}"
            mcp_calls = r.get("tool_calls_mcp")
            reason = "H3/null" if mcp_calls is None else "zero-MCP"
            print(
                f"    {r['task_id'][:50]:50s} {suite:22s} "
                f"{cost_str:>8s} {reward_str:>8s} {calls_str:>6s} {reason:>12s}"
            )
    print()


def main():
    print("Collecting task_metrics.json data from runs/official/...")
    raw_data = collect_task_data()
    n_bl = sum(1 for r in raw_data if r["config"] == "baseline")
    n_sg_raw = sum(1 for r in raw_data if r["config"] == "sourcegraph_full")
    print(f"Collected {len(raw_data)} task records (after dedup and skip filters)")
    print(f"  baseline:         {n_bl}")
    print(f"  sourcegraph_full: {n_sg_raw}")

    # Separate zero-MCP SG_full runs (invalid treatment data)
    flagged = [r for r in raw_data if _is_zero_mcp_sg(r)]
    data = [r for r in raw_data if not _is_zero_mcp_sg(r)]

    n_sg_valid = sum(1 for r in data if r["config"] == "sourcegraph_full")
    print(f"\n  EXCLUDED: {len(flagged)} zero-MCP SG_full runs (invalid treatment)")
    print(f"  Valid for analysis: {n_bl} baseline + {n_sg_valid} SG_full = {len(data)} tasks")
    print()

    # Run all analyses on valid data only
    a = analysis_a_token_breakdown(data)
    b = analysis_b_cost_mcp_correlation(data)
    c = analysis_c_suite_breakdown(data)
    d = analysis_d_paired_tasks(data)
    e = analysis_e_mcp_overhead(data)

    # Print results
    print_analysis_a(a)
    print_analysis_b(b)
    print_analysis_c(c)
    print_analysis_d(d)
    print_analysis_e(e)
    print_outlier_analysis(data)
    if flagged:
        print_flagged_runs(flagged)

    # Save raw JSON
    output = {
        "token_breakdown": a,
        "cost_mcp_correlation": b,
        "suite_breakdown": c,
        "paired_tasks": d,
        "mcp_overhead": e,
        "flagged_zero_mcp": [
            {"task_id": r["task_id"], "suite": r["suite"],
             "cost_usd": r["cost_usd"], "reward": r.get("reward"),
             "tool_calls_mcp": r.get("tool_calls_mcp"),
             "tool_calls_total": r.get("tool_calls_total")}
            for r in flagged
        ],
    }

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps(output, indent=2, default=str))
    print(f"Raw data saved to {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
