#!/usr/bin/env python3
"""
Comprehensive multi-dimensional analysis of CodeScaleBench benchmark results.

Loads MANIFEST.json, task_metrics.json files, retrieval_metrics.json files,
and selected_benchmark_tasks.json, then computes:
  1. Score Distribution Analysis
  2. Paired Config Comparison (MCP Impact)
  3. IR Retrieval Analysis
  4. Multi-Dimensional Analysis
  5. Key Findings Summary

Outputs:
  - Rich human-readable report to stdout
  - JSON report to runs/official/comprehensive_analysis.json

Usage:
    python3 scripts/comprehensive_analysis.py

Dependencies: stdlib only (no external libraries).
"""

import json
import os
import glob
import math
import re
import statistics
from collections import defaultdict, Counter
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
OFFICIAL = ROOT / "runs" / "official"
MANIFEST_PATH = OFFICIAL / "MANIFEST.json"
SELECTED_TASKS_PATH = ROOT / "configs" / "selected_benchmark_tasks.json"
AGGREGATE_RETRIEVAL_PATH = OFFICIAL / "retrieval_events_aggregate" / "run_retrieval_summary.json"
OUTPUT_JSON_PATH = OFFICIAL / "comprehensive_analysis.json"

BASELINE_CONFIGS = {"baseline", "baseline-local-direct", "baseline-local-artifact"}
MCP_CONFIGS = {"mcp", "mcp-remote-direct", "mcp-remote-artifact"}

DELTA_THRESHOLD = 0.05  # threshold for "helps" / "hurts" classification

CONTEXT_LENGTH_BINS = [
    (0, 100_000, "<100K"),
    (100_000, 500_000, "100K-500K"),
    (500_000, float("inf"), ">500K"),
]

MCP_RATIO_BINS = [
    (0, 0.01, "0%"),
    (0.01, 0.25, "1-25%"),
    (0.25, 0.50, "25-50%"),
    (0.50, 0.75, "50-75%"),
    (0.75, 1.01, "75-100%"),
]


# ---------------------------------------------------------------------------
# Utility: statistics helpers (stdlib only)
# ---------------------------------------------------------------------------

def safe_mean(vals):
    """Return mean or None for empty list."""
    if not vals:
        return None
    return sum(vals) / len(vals)


def safe_median(vals):
    """Return median or None."""
    if not vals:
        return None
    return statistics.median(vals)


def safe_stdev(vals):
    """Return population stdev or None."""
    if len(vals) < 2:
        return None
    return statistics.stdev(vals)


def pearson_r(xs, ys):
    """Compute Pearson correlation coefficient. Return None if degenerate."""
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs) / n)
    sy = math.sqrt(sum((y - my) ** 2 for y in ys) / n)
    if sx == 0 or sy == 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / n
    return cov / (sx * sy)


def wilcoxon_signed_rank(diffs):
    """
    Simplified Wilcoxon signed-rank test (two-sided).
    Returns (W_stat, n_nonzero, approx_z) or None if not enough data.
    Uses normal approximation for n >= 10.
    """
    nonzero = [(abs(d), d) for d in diffs if d != 0]
    n = len(nonzero)
    if n < 5:
        return None
    # Rank by absolute value
    nonzero.sort(key=lambda x: x[0])
    ranks = list(range(1, n + 1))
    # Handle ties: assign average rank
    i = 0
    while i < n:
        j = i
        while j < n and nonzero[j][0] == nonzero[i][0]:
            j += 1
        avg_rank = sum(ranks[i:j]) / (j - i)
        for k in range(i, j):
            ranks[k] = avg_rank
        i = j
    # Compute W+ (sum of ranks for positive differences)
    w_plus = sum(r for (_, d), r in zip(nonzero, ranks) if d > 0)
    w_minus = sum(r for (_, d), r in zip(nonzero, ranks) if d < 0)
    w_stat = min(w_plus, w_minus)
    # Normal approximation
    mean_w = n * (n + 1) / 4
    std_w = math.sqrt(n * (n + 1) * (2 * n + 1) / 24)
    if std_w == 0:
        return (w_stat, n, 0.0)
    z = (w_stat - mean_w) / std_w
    return (w_stat, n, z)


def histogram_buckets(vals, n_buckets=10):
    """Create histogram from values. Returns list of (lo, hi, count)."""
    if not vals:
        return []
    lo = min(vals)
    hi = max(vals)
    if lo == hi:
        return [(lo, hi, len(vals))]
    width = (hi - lo) / n_buckets
    buckets = []
    for i in range(n_buckets):
        b_lo = lo + i * width
        b_hi = lo + (i + 1) * width
        count = sum(1 for v in vals if b_lo <= v < b_hi or (i == n_buckets - 1 and v == b_hi))
        buckets.append((b_lo, b_hi, count))
    return buckets


def bin_value(val, bins):
    """Assign val to a labelled bin. Returns label or 'unknown'."""
    if val is None:
        return "unknown"
    for lo, hi, label in bins:
        if lo <= val < hi:
            return label
    return "unknown"


# ---------------------------------------------------------------------------
# Utility: formatting helpers
# ---------------------------------------------------------------------------

SECTION_WIDTH = 90


def section_header(title, char="="):
    """Print a section header."""
    print()
    print(char * SECTION_WIDTH)
    print(f"  {title}")
    print(char * SECTION_WIDTH)


def sub_header(title, char="-"):
    print()
    print(f"  {title}")
    print(f"  {char * len(title)}")


def table_row(cols, widths):
    """Format a row with fixed-width columns."""
    parts = []
    for col, w in zip(cols, widths):
        s = str(col) if col is not None else "N/A"
        if w < 0:
            parts.append(s.ljust(-w))
        else:
            parts.append(s.rjust(w))
    return "  " + "  ".join(parts)


def fmt_pct(val, decimals=1):
    if val is None:
        return "N/A"
    return f"{val * 100:.{decimals}f}%"


def fmt_float(val, decimals=3):
    if val is None:
        return "N/A"
    return f"{val:.{decimals}f}"


def fmt_int(val):
    if val is None:
        return "N/A"
    return f"{val:,}"


# ---------------------------------------------------------------------------
# Task ID normalization
# ---------------------------------------------------------------------------

def normalize_task_id(raw_id):
    """
    Normalize a task ID by:
      1. Stripping leading bl_ or mcp_ prefix
      2. Stripping trailing _XxXxXx hash suffix (5-7 alphanumeric after last _)
      3. Lowercasing
    """
    tid = raw_id
    # Strip prefix
    if tid.startswith("bl_"):
        tid = tid[3:]
    elif tid.startswith("mcp_"):
        tid = tid[4:]
    # Strip trailing hash suffix: pattern _<5-7 alnum> at end
    # But be careful not to strip legitimate suffixes like -001
    m = re.match(r"^(.+?)_([A-Za-z0-9]{5,7})$", tid)
    if m:
        tid = m.group(1)
    return tid.lower()


def config_type(config_name):
    """Classify a config name as 'baseline' or 'mcp'."""
    if config_name in BASELINE_CONFIGS:
        return "baseline"
    if config_name in MCP_CONFIGS:
        return "mcp"
    if "baseline" in config_name.lower():
        return "baseline"
    if "mcp" in config_name.lower():
        return "mcp"
    return "unknown"


def extract_suite_from_benchmark(benchmark):
    """Extract suite name from benchmark field."""
    if not benchmark:
        return "unknown"
    return benchmark


def extract_suite_family(suite):
    """Group suites into SDLC vs org-scale."""
    if suite.startswith(("csb_org_", "ccb_mcp_")):
        return "org"
    elif suite.startswith(("csb_sdlc_", "ccb_")):
        return "sdlc"
    return "other"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_manifest():
    """Load MANIFEST.json and return runs dict."""
    if not MANIFEST_PATH.exists():
        print(f"WARNING: {MANIFEST_PATH} not found. MANIFEST analysis will be empty.")
        return {}
    with open(MANIFEST_PATH) as f:
        data = json.load(f)
    return data.get("runs", {})


def load_task_metrics():
    """
    Scan all task_metrics.json files under runs/official/.
    Returns list of dicts, each augmented with:
      - _normalized_task_id
      - _config_type ('baseline' or 'mcp')
    """
    pattern = str(OFFICIAL / "**" / "task_metrics.json")
    paths = glob.glob(pattern, recursive=True)
    records = []
    for p in paths:
        try:
            with open(p) as f:
                d = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        d["_source_path"] = p
        d["_normalized_task_id"] = normalize_task_id(d.get("task_id", ""))
        cn = d.get("config_name", "")
        d["_config_type"] = config_type(cn)
        records.append(d)
    return records


def load_retrieval_metrics():
    """
    Scan all *.retrieval_metrics.json files under runs/official/.
    Returns list of dicts augmented with provenance-derived fields.
    """
    pattern = str(OFFICIAL / "**" / "*.retrieval_metrics.json")
    paths = glob.glob(pattern, recursive=True)
    records = []
    for p in paths:
        try:
            with open(p) as f:
                d = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        prov = d.get("provenance", {})
        d["_task_name"] = prov.get("task_name", "")
        d["_config_name"] = prov.get("config_name", "")
        d["_config_type"] = config_type(prov.get("config_name", ""))
        d["_normalized_task_id"] = normalize_task_id(prov.get("task_name", ""))
        d["_source_path"] = p
        records.append(d)
    return records


def load_selected_tasks():
    """Load selected_benchmark_tasks.json as a dict keyed by normalized task_id."""
    if not SELECTED_TASKS_PATH.exists():
        print(f"WARNING: {SELECTED_TASKS_PATH} not found.")
        return {}
    with open(SELECTED_TASKS_PATH) as f:
        data = json.load(f)
    tasks = data.get("tasks", [])
    by_id = {}
    for t in tasks:
        norm = normalize_task_id(t.get("task_id", ""))
        by_id[norm] = t
    return by_id


def load_aggregate_retrieval():
    """Load the pre-computed aggregate retrieval summary."""
    if not AGGREGATE_RETRIEVAL_PATH.exists():
        return {}
    with open(AGGREGATE_RETRIEVAL_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Enrichment: merge selected task metadata into task_metrics
# ---------------------------------------------------------------------------

def enrich_task_metrics(task_metrics, selected_tasks):
    """
    Fill in missing metadata fields from selected_benchmark_tasks.json.
    """
    for tm in task_metrics:
        norm_id = tm["_normalized_task_id"]
        sel = selected_tasks.get(norm_id, {})
        for field in [
            "sdlc_phase", "language", "difficulty", "category", "repo",
            "mcp_benefit_score", "mcp_breakdown",
        ]:
            if tm.get(field) is None and sel.get(field) is not None:
                tm[field] = sel[field]
        if tm.get("task_context_length") is None and sel.get("context_length") is not None:
            tm["task_context_length"] = sel["context_length"]
        if tm.get("task_files_count") is None and sel.get("files_count") is not None:
            tm["task_files_count"] = sel["files_count"]
        if tm.get("benchmark") is None and sel.get("benchmark") is not None:
            tm["benchmark"] = sel["benchmark"]
        # Add org-scale flag (reads legacy "mcp_unique" key from config)
        tm["_mcp_unique"] = sel.get("mcp_unique", False)


# ---------------------------------------------------------------------------
# Filter: exclude errored / zero-token tasks
# ---------------------------------------------------------------------------

def is_valid_for_analysis(tm):
    """Return True if the task should be included in reward analysis."""
    status = tm.get("status", "")
    if status == "error":
        return False
    # Zero-token tasks: no agent output at all
    inp = tm.get("input_tokens") or 0
    outp = tm.get("output_tokens") or 0
    if inp == 0 and outp == 0:
        return False
    return True


# ---------------------------------------------------------------------------
# Deduplication: if multiple metrics files for same (task_id, config_name),
# keep the latest (by wall_clock or path timestamp heuristic).
# ---------------------------------------------------------------------------

def deduplicate_task_metrics(records):
    """
    Keep one record per (normalized_task_id, config_name).
    Prefer higher reward, then longer wall_clock_seconds (proxy for most complete run).
    """
    grouped = defaultdict(list)
    for r in records:
        key = (r["_normalized_task_id"], r.get("config_name", ""))
        grouped[key].append(r)

    deduped = []
    for key, recs in grouped.items():
        if len(recs) == 1:
            deduped.append(recs[0])
        else:
            # Sort by reward desc, then wall_clock desc
            recs.sort(key=lambda r: (
                r.get("reward") or 0,
                r.get("wall_clock_seconds") or 0,
            ), reverse=True)
            deduped.append(recs[0])
    return deduped


# ---------------------------------------------------------------------------
# Section 1: Score Distribution Analysis
# ---------------------------------------------------------------------------

def analyze_score_distribution(task_metrics, manifest_runs, report):
    section_header("SECTION 1: Score Distribution Analysis")
    report["section_1_score_distribution"] = {}

    valid = [tm for tm in task_metrics if is_valid_for_analysis(tm)]
    all_rewards = [tm["reward"] for tm in valid if tm.get("reward") is not None]

    # 1a. Overall distribution
    sub_header("1a. Overall Reward Distribution")
    if all_rewards:
        buckets = histogram_buckets(all_rewards, n_buckets=10)
        widths = [-12, 8, 8]
        print(table_row(["Bucket", "Count", "Pct"], widths))
        print(table_row(["------", "-----", "---"], widths))
        for lo, hi, cnt in buckets:
            lbl = f"[{lo:.2f}, {hi:.2f})"
            pct = f"{cnt / len(all_rewards) * 100:.1f}%"
            print(table_row([lbl, cnt, pct], widths))
        print()
        print(f"  Total valid tasks: {len(all_rewards)}")
        print(f"  Mean reward:       {safe_mean(all_rewards):.4f}")
        print(f"  Median reward:     {safe_median(all_rewards):.4f}")
        print(f"  Stdev:             {fmt_float(safe_stdev(all_rewards), 4)}")
        print(f"  Min:               {min(all_rewards):.4f}")
        print(f"  Max:               {max(all_rewards):.4f}")
        report["section_1_score_distribution"]["overall"] = {
            "n": len(all_rewards),
            "mean": safe_mean(all_rewards),
            "median": safe_median(all_rewards),
            "stdev": safe_stdev(all_rewards),
            "min": min(all_rewards),
            "max": max(all_rewards),
            "histogram": [{"lo": lo, "hi": hi, "count": cnt} for lo, hi, cnt in buckets],
        }
    else:
        print("  No valid reward data found.")
        report["section_1_score_distribution"]["overall"] = {"n": 0}

    # 1b. By suite
    sub_header("1b. Reward by Suite")
    suite_rewards = defaultdict(list)
    for tm in valid:
        suite = tm.get("benchmark", "unknown") or "unknown"
        r = tm.get("reward")
        if r is not None:
            suite_rewards[suite].append(r)

    widths = [-30, 6, 8, 8, 8]
    print(table_row(["Suite", "N", "Mean", "Median", "Stdev"], widths))
    print(table_row(["-----", "--", "----", "------", "-----"], widths))
    suite_summary = {}
    for suite in sorted(suite_rewards.keys()):
        vals = suite_rewards[suite]
        row = [suite, len(vals), fmt_float(safe_mean(vals)), fmt_float(safe_median(vals)),
               fmt_float(safe_stdev(vals))]
        print(table_row(row, widths))
        suite_summary[suite] = {
            "n": len(vals), "mean": safe_mean(vals),
            "median": safe_median(vals), "stdev": safe_stdev(vals),
        }
    report["section_1_score_distribution"]["by_suite"] = suite_summary

    # 1c. By config type
    sub_header("1c. Reward by Config Type")
    config_rewards = defaultdict(list)
    for tm in valid:
        ct = tm["_config_type"]
        r = tm.get("reward")
        if r is not None:
            config_rewards[ct].append(r)

    widths = [-20, 6, 8, 8, 8]
    print(table_row(["Config Type", "N", "Mean", "Median", "Stdev"], widths))
    print(table_row(["-----------", "--", "----", "------", "-----"], widths))
    config_summary = {}
    for ct in sorted(config_rewards.keys()):
        vals = config_rewards[ct]
        row = [ct, len(vals), fmt_float(safe_mean(vals)), fmt_float(safe_median(vals)),
               fmt_float(safe_stdev(vals))]
        print(table_row(row, widths))
        config_summary[ct] = {
            "n": len(vals), "mean": safe_mean(vals),
            "median": safe_median(vals), "stdev": safe_stdev(vals),
        }
    report["section_1_score_distribution"]["by_config_type"] = config_summary

    # 1d. By model
    sub_header("1d. Reward by Model (from MANIFEST)")
    model_rewards = defaultdict(list)
    for run_key, run_data in manifest_runs.items():
        model = run_data.get("model", "unknown")
        for tid, tdata in run_data.get("tasks", {}).items():
            r = tdata.get("reward")
            status = tdata.get("status", "")
            if r is not None and status != "error":
                model_rewards[model].append(r)

    widths = [-50, 6, 8, 8]
    print(table_row(["Model", "N", "Mean", "Median"], widths))
    print(table_row(["-----", "--", "----", "------"], widths))
    model_summary = {}
    for model in sorted(model_rewards.keys()):
        vals = model_rewards[model]
        row = [model, len(vals), fmt_float(safe_mean(vals)), fmt_float(safe_median(vals))]
        print(table_row(row, widths))
        model_summary[model] = {
            "n": len(vals), "mean": safe_mean(vals), "median": safe_median(vals),
        }
    report["section_1_score_distribution"]["by_model"] = model_summary

    # 1e. Exclusion summary
    sub_header("1e. Exclusion Summary")
    total = len(task_metrics)
    errored = sum(1 for tm in task_metrics if tm.get("status") == "error")
    zero_tok = sum(
        1 for tm in task_metrics
        if (tm.get("input_tokens") or 0) == 0 and (tm.get("output_tokens") or 0) == 0
        and tm.get("status") != "error"
    )
    timed_out = sum(1 for tm in task_metrics if _get_error_fingerprint_id(tm) == "timeout")
    print(f"  Total task_metrics records:  {total}")
    print(f"  After dedup:                 {len(task_metrics)}")
    print(f"  Errored (excluded):          {errored}")
    print(f"  Zero-token (excluded):       {zero_tok}")
    print(f"  Timed out:                   {timed_out}")
    print(f"  Valid for analysis:          {len(valid)}")
    report["section_1_score_distribution"]["exclusions"] = {
        "total_records": total,
        "errored": errored,
        "zero_token": zero_tok,
        "timed_out": timed_out,
        "valid": len(valid),
    }


def _get_error_fingerprint_id(tm):
    ef = tm.get("error_fingerprint")
    if isinstance(ef, dict):
        return ef.get("fingerprint_id", "")
    return ""


# ---------------------------------------------------------------------------
# Section 2: Paired Config Comparison (MCP Impact)
# ---------------------------------------------------------------------------

def analyze_mcp_impact(task_metrics, selected_tasks, report):
    section_header("SECTION 2: Paired Config Comparison (MCP Impact)")
    report["section_2_mcp_impact"] = {}

    valid = [tm for tm in task_metrics if is_valid_for_analysis(tm)]

    # Build lookup: normalized_task_id -> {config_type -> record}
    task_configs = defaultdict(dict)
    for tm in valid:
        norm_id = tm["_normalized_task_id"]
        ct = tm["_config_type"]
        if ct in ("baseline", "mcp"):
            # If multiple configs of same type, keep best by reward
            existing = task_configs[norm_id].get(ct)
            if existing is None or (tm.get("reward") or 0) > (existing.get("reward") or 0):
                task_configs[norm_id][ct] = tm

    # Find paired tasks
    paired = {}
    for norm_id, configs in task_configs.items():
        if "baseline" in configs and "mcp" in configs:
            bl_reward = configs["baseline"].get("reward")
            mcp_reward = configs["mcp"].get("reward")
            if bl_reward is not None and mcp_reward is not None:
                delta = mcp_reward - bl_reward
                paired[norm_id] = {
                    "baseline_reward": bl_reward,
                    "mcp_reward": mcp_reward,
                    "delta": delta,
                    "baseline_config": configs["baseline"].get("config_name"),
                    "mcp_config": configs["mcp"].get("config_name"),
                    "benchmark": configs["baseline"].get("benchmark") or configs["mcp"].get("benchmark"),
                    "difficulty": configs["baseline"].get("difficulty") or configs["mcp"].get("difficulty"),
                    "language": configs["baseline"].get("language") or configs["mcp"].get("language"),
                    "context_length": (
                        configs["baseline"].get("task_context_length")
                        or configs["mcp"].get("task_context_length")
                    ),
                    "mcp_benefit_score": (
                        configs["baseline"].get("mcp_benefit_score")
                        or configs["mcp"].get("mcp_benefit_score")
                    ),
                }

    sub_header("2a. Overall Paired Comparison")
    n_paired = len(paired)
    if n_paired == 0:
        print("  No paired tasks found.")
        report["section_2_mcp_impact"]["n_paired"] = 0
        return

    deltas = [p["delta"] for p in paired.values()]
    helps = sum(1 for d in deltas if d > DELTA_THRESHOLD)
    hurts = sum(1 for d in deltas if d < -DELTA_THRESHOLD)
    neutral = n_paired - helps - hurts

    print(f"  Paired tasks:          {n_paired}")
    print(f"  Mean delta:            {safe_mean(deltas):+.4f}")
    print(f"  Median delta:          {safe_median(deltas):+.4f}")
    print(f"  Stdev delta:           {fmt_float(safe_stdev(deltas), 4)}")
    print(f"  MCP helps (>{DELTA_THRESHOLD:+.2f}):  {helps} ({helps/n_paired*100:.1f}%)")
    print(f"  MCP hurts (<{-DELTA_THRESHOLD:+.2f}):  {hurts} ({hurts/n_paired*100:.1f}%)")
    print(f"  Neutral:               {neutral} ({neutral/n_paired*100:.1f}%)")

    # Wilcoxon test
    wilcoxon = wilcoxon_signed_rank(deltas)
    if wilcoxon:
        w_stat, n_nz, z = wilcoxon
        print(f"\n  Wilcoxon signed-rank test (normal approx.):")
        print(f"    W = {w_stat:.1f}, n_nonzero = {n_nz}, z = {z:.3f}")
        sig = abs(z) > 1.96
        print(f"    {'Significant' if sig else 'Not significant'} at alpha=0.05 (|z| {'>' if sig else '<='} 1.96)")

    report["section_2_mcp_impact"]["overall"] = {
        "n_paired": n_paired,
        "mean_delta": safe_mean(deltas),
        "median_delta": safe_median(deltas),
        "stdev_delta": safe_stdev(deltas),
        "mcp_helps": helps,
        "mcp_hurts": hurts,
        "neutral": neutral,
        "wilcoxon": {
            "w_stat": wilcoxon[0] if wilcoxon else None,
            "n_nonzero": wilcoxon[1] if wilcoxon else None,
            "z": wilcoxon[2] if wilcoxon else None,
        },
    }

    # 2b. MCP impact by suite
    sub_header("2b. MCP Impact by Suite")
    suite_deltas = defaultdict(list)
    for norm_id, p in paired.items():
        suite = p.get("benchmark", "unknown") or "unknown"
        suite_deltas[suite].append(p["delta"])

    widths = [-30, 5, 9, 9, 6, 6, 6]
    print(table_row(["Suite", "N", "Mean d", "Med d", "Help", "Hurt", "Neut"], widths))
    print(table_row(["-----", "--", "------", "-----", "----", "----", "----"], widths))
    suite_impact = {}
    for suite in sorted(suite_deltas.keys()):
        ds = suite_deltas[suite]
        h = sum(1 for d in ds if d > DELTA_THRESHOLD)
        hu = sum(1 for d in ds if d < -DELTA_THRESHOLD)
        ne = len(ds) - h - hu
        print(table_row([
            suite, len(ds), f"{safe_mean(ds):+.4f}", f"{safe_median(ds):+.4f}",
            h, hu, ne,
        ], widths))
        suite_impact[suite] = {
            "n": len(ds), "mean_delta": safe_mean(ds), "median_delta": safe_median(ds),
            "helps": h, "hurts": hu, "neutral": ne,
        }
    report["section_2_mcp_impact"]["by_suite"] = suite_impact

    # 2c. MCP impact by difficulty
    sub_header("2c. MCP Impact by Difficulty")
    diff_deltas = defaultdict(list)
    for norm_id, p in paired.items():
        diff = p.get("difficulty", "unknown") or "unknown"
        diff_deltas[diff].append(p["delta"])

    widths = [-15, 5, 9, 9, 6, 6, 6]
    print(table_row(["Difficulty", "N", "Mean d", "Med d", "Help", "Hurt", "Neut"], widths))
    print(table_row(["----------", "--", "------", "-----", "----", "----", "----"], widths))
    diff_impact = {}
    for diff in sorted(diff_deltas.keys()):
        ds = diff_deltas[diff]
        h = sum(1 for d in ds if d > DELTA_THRESHOLD)
        hu = sum(1 for d in ds if d < -DELTA_THRESHOLD)
        ne = len(ds) - h - hu
        print(table_row([
            diff, len(ds), f"{safe_mean(ds):+.4f}", f"{safe_median(ds):+.4f}",
            h, hu, ne,
        ], widths))
        diff_impact[diff] = {
            "n": len(ds), "mean_delta": safe_mean(ds), "median_delta": safe_median(ds),
            "helps": h, "hurts": hu, "neutral": ne,
        }
    report["section_2_mcp_impact"]["by_difficulty"] = diff_impact

    # 2d. MCP impact by language
    sub_header("2d. MCP Impact by Language")
    lang_deltas = defaultdict(list)
    for norm_id, p in paired.items():
        lang = (p.get("language") or "unknown").lower()
        lang_deltas[lang].append(p["delta"])

    widths = [-15, 5, 9, 9]
    print(table_row(["Language", "N", "Mean d", "Med d"], widths))
    print(table_row(["--------", "--", "------", "-----"], widths))
    lang_impact = {}
    for lang in sorted(lang_deltas.keys()):
        ds = lang_deltas[lang]
        print(table_row([
            lang, len(ds), f"{safe_mean(ds):+.4f}", f"{safe_median(ds):+.4f}",
        ], widths))
        lang_impact[lang] = {"n": len(ds), "mean_delta": safe_mean(ds), "median_delta": safe_median(ds)}
    report["section_2_mcp_impact"]["by_language"] = lang_impact

    # 2e. MCP impact by context length bucket
    sub_header("2e. MCP Impact by Context Length")
    ctx_deltas = defaultdict(list)
    for norm_id, p in paired.items():
        ctx = p.get("context_length")
        bucket = bin_value(ctx, CONTEXT_LENGTH_BINS)
        ctx_deltas[bucket].append(p["delta"])

    widths = [-15, 5, 9, 9]
    print(table_row(["Ctx Length", "N", "Mean d", "Med d"], widths))
    print(table_row(["----------", "--", "------", "-----"], widths))
    ctx_impact = {}
    for bucket in ["<100K", "100K-500K", ">500K", "unknown"]:
        if bucket not in ctx_deltas:
            continue
        ds = ctx_deltas[bucket]
        print(table_row([
            bucket, len(ds), f"{safe_mean(ds):+.4f}", f"{safe_median(ds):+.4f}",
        ], widths))
        ctx_impact[bucket] = {"n": len(ds), "mean_delta": safe_mean(ds), "median_delta": safe_median(ds)}
    report["section_2_mcp_impact"]["by_context_length"] = ctx_impact

    # 2f. Predicted vs actual MCP benefit correlation
    sub_header("2f. Predicted vs Actual MCP Benefit")
    pred_vals = []
    actual_vals = []
    for norm_id, p in paired.items():
        pred = p.get("mcp_benefit_score")
        if pred is not None:
            pred_vals.append(pred)
            actual_vals.append(p["delta"])

    if len(pred_vals) >= 3:
        r = pearson_r(pred_vals, actual_vals)
        print(f"  Paired tasks with mcp_benefit_score: {len(pred_vals)}")
        print(f"  Pearson r (predicted vs actual delta): {fmt_float(r, 4)}")
        report["section_2_mcp_impact"]["predicted_vs_actual"] = {
            "n": len(pred_vals),
            "pearson_r": r,
        }
    else:
        print(f"  Insufficient data for correlation ({len(pred_vals)} tasks with mcp_benefit_score).")
        report["section_2_mcp_impact"]["predicted_vs_actual"] = {"n": len(pred_vals), "pearson_r": None}

    # Store paired data for later use
    report["_paired_data"] = paired


# ---------------------------------------------------------------------------
# Section 3: IR Retrieval Analysis
# ---------------------------------------------------------------------------

def analyze_ir_retrieval(retrieval_metrics, task_metrics, report):
    section_header("SECTION 3: IR Retrieval Analysis")
    report["section_3_ir_retrieval"] = {}

    # 3a. File-level metrics by config type
    sub_header("3a. File-Level Retrieval Metrics by Config Type")
    config_ir = defaultdict(lambda: defaultdict(list))
    for rm in retrieval_metrics:
        ct = rm["_config_type"]
        flm = rm.get("file_level_metrics", {})
        if not flm or not flm.get("computable"):
            continue
        for metric in ["mrr", "map_score", "file_recall", "context_efficiency"]:
            val = flm.get(metric)
            if val is not None:
                config_ir[ct][metric].append(val)
        # Precision/Recall @K
        for k in [1, 3, 5, 10]:
            pk = flm.get("precision", {}).get(str(k))
            rk = flm.get("recall", {}).get(str(k))
            if pk is not None:
                config_ir[ct][f"precision@{k}"].append(pk)
            if rk is not None:
                config_ir[ct][f"recall@{k}"].append(rk)

    metrics_to_show = ["mrr", "map_score", "file_recall", "context_efficiency",
                       "precision@1", "precision@5", "recall@1", "recall@5"]
    widths = [-22, 8, 8, 8, 8, 8]
    print(table_row(["Metric", "BL N", "BL Mean", "MCP N", "MCP Mean", "Delta"], widths))
    print(table_row(["------", "----", "-------", "-----", "--------", "-----"], widths))
    ir_by_config = {}
    for metric in metrics_to_show:
        bl_vals = config_ir.get("baseline", {}).get(metric, [])
        mcp_vals = config_ir.get("mcp", {}).get(metric, [])
        bl_mean = safe_mean(bl_vals)
        mcp_mean = safe_mean(mcp_vals)
        delta = None
        if bl_mean is not None and mcp_mean is not None:
            delta = mcp_mean - bl_mean
        print(table_row([
            metric,
            len(bl_vals),
            fmt_float(bl_mean),
            len(mcp_vals),
            fmt_float(mcp_mean),
            f"{delta:+.4f}" if delta is not None else "N/A",
        ], widths))
        ir_by_config[metric] = {
            "baseline": {"n": len(bl_vals), "mean": bl_mean},
            "mcp": {"n": len(mcp_vals), "mean": mcp_mean},
            "delta": delta,
        }
    report["section_3_ir_retrieval"]["file_level_by_config"] = ir_by_config

    # 3b. Correlation between IR metrics and reward
    sub_header("3b. Correlation: IR Metrics vs Reward")
    # Build a lookup from (normalized_task_id, config_type) -> reward
    reward_lookup = {}
    for tm in task_metrics:
        if is_valid_for_analysis(tm) and tm.get("reward") is not None:
            key = (tm["_normalized_task_id"], tm["_config_type"])
            reward_lookup[key] = tm["reward"]

    ir_reward_corr = {}
    widths = [-22, 6, 10]
    print(table_row(["IR Metric", "N", "Pearson r"], widths))
    print(table_row(["---------", "--", "---------"], widths))
    for metric in ["mrr", "map_score", "file_recall", "context_efficiency",
                    "precision@5", "recall@5"]:
        xs = []
        ys = []
        for rm in retrieval_metrics:
            flm = rm.get("file_level_metrics", {})
            if not flm or not flm.get("computable"):
                continue
            if metric.startswith("precision@") or metric.startswith("recall@"):
                parts = metric.split("@")
                val = flm.get(parts[0], {}).get(parts[1])
            else:
                val = flm.get(metric)
            if val is None:
                continue
            key = (rm["_normalized_task_id"], rm["_config_type"])
            reward = reward_lookup.get(key)
            if reward is not None:
                xs.append(val)
                ys.append(reward)
        r = pearson_r(xs, ys)
        print(table_row([metric, len(xs), fmt_float(r, 4)], widths))
        ir_reward_corr[metric] = {"n": len(xs), "pearson_r": r}
    report["section_3_ir_retrieval"]["ir_reward_correlation"] = ir_reward_corr

    # 3c. MCP tool usage breakdown
    sub_header("3c. MCP Tool Usage vs Reward")
    tool_rewards = defaultdict(list)
    mcp_tool_counts = Counter()
    for tm in task_metrics:
        if not is_valid_for_analysis(tm):
            continue
        if tm["_config_type"] != "mcp":
            continue
        r = tm.get("reward")
        if r is None:
            continue
        tool_calls_by_name = tm.get("tool_calls_by_name") or {}
        for tool_name, count in tool_calls_by_name.items():
            if "sourcegraph" in tool_name.lower() or "mcp" in tool_name.lower():
                mcp_tool_counts[tool_name] += count
                tool_rewards[tool_name].append(r)

    if tool_rewards:
        widths = [-55, 6, 8, 8, 8]
        print(table_row(["MCP Tool", "Tasks", "Calls", "Mean R", "Med R"], widths))
        print(table_row(["--------", "-----", "-----", "------", "-----"], widths))
        tool_analysis = {}
        for tool in sorted(tool_rewards.keys(), key=lambda t: -len(tool_rewards[t])):
            vals = tool_rewards[tool]
            print(table_row([
                tool, len(vals), mcp_tool_counts[tool],
                fmt_float(safe_mean(vals)), fmt_float(safe_median(vals)),
            ], widths))
            tool_analysis[tool] = {
                "tasks": len(vals),
                "total_calls": mcp_tool_counts[tool],
                "mean_reward": safe_mean(vals),
                "median_reward": safe_median(vals),
            }
        report["section_3_ir_retrieval"]["mcp_tool_usage"] = tool_analysis
    else:
        print("  No MCP tool usage data found.")
        report["section_3_ir_retrieval"]["mcp_tool_usage"] = {}

    # 3d. Search strategy effectiveness
    sub_header("3d. Search Strategy vs Reward (MCP configs)")
    strategy_rewards = defaultdict(list)
    for tm in task_metrics:
        if not is_valid_for_analysis(tm) or tm["_config_type"] != "mcp":
            continue
        r = tm.get("reward")
        strat = tm.get("search_strategy_type")
        if r is not None and strat:
            strategy_rewards[strat].append(r)

    if strategy_rewards:
        widths = [-25, 6, 8, 8]
        print(table_row(["Strategy", "N", "Mean R", "Med R"], widths))
        print(table_row(["--------", "--", "------", "-----"], widths))
        strat_analysis = {}
        for strat in sorted(strategy_rewards.keys()):
            vals = strategy_rewards[strat]
            print(table_row([strat, len(vals), fmt_float(safe_mean(vals)), fmt_float(safe_median(vals))], widths))
            strat_analysis[strat] = {"n": len(vals), "mean_reward": safe_mean(vals), "median_reward": safe_median(vals)}
        report["section_3_ir_retrieval"]["search_strategy"] = strat_analysis
    else:
        print("  No search strategy data found.")
        report["section_3_ir_retrieval"]["search_strategy"] = {}

    # 3e. Error taxonomy analysis
    sub_header("3e. Error Taxonomy (from Retrieval Metrics)")
    error_counts = Counter()
    error_by_config = {"baseline": Counter(), "mcp": Counter()}
    n_with_errors = 0
    for rm in retrieval_metrics:
        et = rm.get("error_taxonomy", {})
        if not et or not et.get("computable"):
            continue
        labels = et.get("labels", {})
        if not labels:
            continue
        n_with_errors += 1
        ct = rm["_config_type"]
        for label, count in labels.items():
            error_counts[label] += count
            if ct in error_by_config:
                error_by_config[ct][label] += count

    if error_counts:
        widths = [-30, 8, 8, 8]
        print(table_row(["Error Type", "Total", "BL", "MCP"], widths))
        print(table_row(["----------", "-----", "--", "---"], widths))
        error_analysis = {}
        for label in sorted(error_counts.keys(), key=lambda l: -error_counts[l]):
            bl = error_by_config["baseline"].get(label, 0)
            mcp = error_by_config["mcp"].get(label, 0)
            print(table_row([label, error_counts[label], bl, mcp], widths))
            error_analysis[label] = {
                "total": error_counts[label],
                "baseline": bl,
                "mcp": mcp,
            }
        print(f"\n  Tasks with error taxonomy: {n_with_errors}")
        report["section_3_ir_retrieval"]["error_taxonomy"] = error_analysis
    else:
        print("  No error taxonomy data found.")
        report["section_3_ir_retrieval"]["error_taxonomy"] = {}


# ---------------------------------------------------------------------------
# Section 4: Multi-Dimensional Analysis
# ---------------------------------------------------------------------------

def analyze_multi_dimensional(task_metrics, report):
    section_header("SECTION 4: Multi-Dimensional Analysis")
    report["section_4_multi_dimensional"] = {}

    valid = [tm for tm in task_metrics if is_valid_for_analysis(tm) and tm.get("reward") is not None]

    # 4a. Cross-tabulation: reward by (suite x config_type)
    sub_header("4a. Cross-Tab: Mean Reward by Suite x Config")
    cross = defaultdict(lambda: defaultdict(list))
    for tm in valid:
        suite = tm.get("benchmark", "unknown") or "unknown"
        ct = tm["_config_type"]
        cross[suite][ct].append(tm["reward"])

    all_configs = sorted(set(tm["_config_type"] for tm in valid))
    col_w = 10
    header_cols = ["Suite"] + all_configs
    header_widths = [-30] + [col_w] * len(all_configs)
    print(table_row(header_cols, header_widths))
    print(table_row(["-----"] + ["------"] * len(all_configs), header_widths))
    cross_tab = {}
    for suite in sorted(cross.keys()):
        row = [suite]
        suite_data = {}
        for ct in all_configs:
            vals = cross[suite].get(ct, [])
            if vals:
                row.append(f"{safe_mean(vals):.3f}({len(vals)})")
                suite_data[ct] = {"mean": safe_mean(vals), "n": len(vals)}
            else:
                row.append("-")
                suite_data[ct] = {"mean": None, "n": 0}
        print(table_row(row, header_widths))
        cross_tab[suite] = suite_data
    report["section_4_multi_dimensional"]["cross_tab_suite_config"] = cross_tab

    # 4b. Language analysis
    sub_header("4b. Mean Reward by Language")
    lang_data = defaultdict(list)
    lang_config = defaultdict(lambda: defaultdict(list))
    for tm in valid:
        lang = (tm.get("language") or "unknown").lower()
        lang_data[lang].append(tm["reward"])
        lang_config[lang][tm["_config_type"]].append(tm["reward"])

    widths = [-15, 5, 8, 8, 8, 8]
    print(table_row(["Language", "N", "Mean", "Median", "BL Mean", "MCP Mean"], widths))
    print(table_row(["--------", "--", "----", "------", "-------", "--------"], widths))
    lang_analysis = {}
    for lang in sorted(lang_data.keys(), key=lambda l: -len(lang_data[l])):
        vals = lang_data[lang]
        bl = lang_config[lang].get("baseline", [])
        mc = lang_config[lang].get("mcp", [])
        print(table_row([
            lang, len(vals), fmt_float(safe_mean(vals)), fmt_float(safe_median(vals)),
            fmt_float(safe_mean(bl)), fmt_float(safe_mean(mc)),
        ], widths))
        lang_analysis[lang] = {
            "n": len(vals), "mean": safe_mean(vals), "median": safe_median(vals),
            "baseline_mean": safe_mean(bl), "mcp_mean": safe_mean(mc),
        }
    report["section_4_multi_dimensional"]["by_language"] = lang_analysis

    # 4c. Difficulty analysis
    sub_header("4c. Mean Reward by Difficulty")
    diff_data = defaultdict(list)
    diff_config = defaultdict(lambda: defaultdict(list))
    for tm in valid:
        diff = tm.get("difficulty", "unknown") or "unknown"
        diff_data[diff].append(tm["reward"])
        diff_config[diff][tm["_config_type"]].append(tm["reward"])

    widths = [-15, 5, 8, 8, 8, 8]
    print(table_row(["Difficulty", "N", "Mean", "Median", "BL Mean", "MCP Mean"], widths))
    print(table_row(["----------", "--", "----", "------", "-------", "--------"], widths))
    diff_analysis = {}
    for diff in sorted(diff_data.keys()):
        vals = diff_data[diff]
        bl = diff_config[diff].get("baseline", [])
        mc = diff_config[diff].get("mcp", [])
        print(table_row([
            diff, len(vals), fmt_float(safe_mean(vals)), fmt_float(safe_median(vals)),
            fmt_float(safe_mean(bl)), fmt_float(safe_mean(mc)),
        ], widths))
        diff_analysis[diff] = {
            "n": len(vals), "mean": safe_mean(vals), "median": safe_median(vals),
            "baseline_mean": safe_mean(bl), "mcp_mean": safe_mean(mc),
        }
    report["section_4_multi_dimensional"]["by_difficulty"] = diff_analysis

    # 4d. Context length bins vs reward
    sub_header("4d. Reward by Codebase Context Length")
    ctx_data = defaultdict(list)
    for tm in valid:
        ctx = tm.get("task_context_length")
        bucket = bin_value(ctx, CONTEXT_LENGTH_BINS)
        ctx_data[bucket].append(tm["reward"])

    widths = [-15, 5, 8, 8]
    print(table_row(["Ctx Length", "N", "Mean", "Median"], widths))
    print(table_row(["----------", "--", "----", "------"], widths))
    ctx_analysis = {}
    for bucket in ["<100K", "100K-500K", ">500K", "unknown"]:
        if bucket not in ctx_data:
            continue
        vals = ctx_data[bucket]
        print(table_row([bucket, len(vals), fmt_float(safe_mean(vals)), fmt_float(safe_median(vals))], widths))
        ctx_analysis[bucket] = {"n": len(vals), "mean": safe_mean(vals), "median": safe_median(vals)}
    report["section_4_multi_dimensional"]["by_context_length"] = ctx_analysis

    # 4e. Files count bins vs reward
    sub_header("4e. Reward by Files Count")
    files_bins = [
        (0, 5, "1-4"),
        (5, 10, "5-9"),
        (10, 20, "10-19"),
        (20, 50, "20-49"),
        (50, float("inf"), "50+"),
    ]
    files_data = defaultdict(list)
    for tm in valid:
        fc = tm.get("task_files_count")
        bucket = bin_value(fc, files_bins)
        files_data[bucket].append(tm["reward"])

    widths = [-12, 5, 8, 8]
    print(table_row(["Files", "N", "Mean", "Median"], widths))
    print(table_row(["-----", "--", "----", "------"], widths))
    files_analysis = {}
    for bucket in ["1-4", "5-9", "10-19", "20-49", "50+", "unknown"]:
        if bucket not in files_data:
            continue
        vals = files_data[bucket]
        print(table_row([bucket, len(vals), fmt_float(safe_mean(vals)), fmt_float(safe_median(vals))], widths))
        files_analysis[bucket] = {"n": len(vals), "mean": safe_mean(vals), "median": safe_median(vals)}
    report["section_4_multi_dimensional"]["by_files_count"] = files_analysis

    # 4f. MCP ratio buckets vs reward
    sub_header("4f. Reward by MCP Tool Ratio (MCP configs only)")
    mcp_valid = [tm for tm in valid if tm["_config_type"] == "mcp"]
    ratio_data = defaultdict(list)
    for tm in mcp_valid:
        ratio = tm.get("mcp_ratio")
        bucket = bin_value(ratio, MCP_RATIO_BINS)
        ratio_data[bucket].append(tm["reward"])

    widths = [-12, 5, 8, 8]
    print(table_row(["MCP Ratio", "N", "Mean", "Median"], widths))
    print(table_row(["---------", "--", "----", "------"], widths))
    ratio_analysis = {}
    for bucket in ["0%", "1-25%", "25-50%", "50-75%", "75-100%", "unknown"]:
        if bucket not in ratio_data:
            continue
        vals = ratio_data[bucket]
        print(table_row([bucket, len(vals), fmt_float(safe_mean(vals)), fmt_float(safe_median(vals))], widths))
        ratio_analysis[bucket] = {"n": len(vals), "mean": safe_mean(vals), "median": safe_median(vals)}
    report["section_4_multi_dimensional"]["by_mcp_ratio"] = ratio_analysis

    # 4g. Cost analysis
    sub_header("4g. Cost vs Reward")
    cost_bins = [
        (0, 0.05, "<$0.05"),
        (0.05, 0.10, "$0.05-0.10"),
        (0.10, 0.25, "$0.10-0.25"),
        (0.25, 0.50, "$0.25-0.50"),
        (0.50, 1.00, "$0.50-1.00"),
        (1.00, float("inf"), ">$1.00"),
    ]
    cost_data = defaultdict(list)
    cost_xs, cost_ys = [], []
    for tm in valid:
        cost = tm.get("cost_usd")
        if cost is not None and cost > 0:
            bucket = bin_value(cost, cost_bins)
            cost_data[bucket].append(tm["reward"])
            cost_xs.append(cost)
            cost_ys.append(tm["reward"])

    widths = [-15, 5, 8, 8]
    print(table_row(["Cost Bucket", "N", "Mean R", "Med R"], widths))
    print(table_row(["-----------", "--", "------", "-----"], widths))
    cost_analysis = {}
    for bucket in ["<$0.05", "$0.05-0.10", "$0.10-0.25", "$0.25-0.50", "$0.50-1.00", ">$1.00"]:
        if bucket not in cost_data:
            continue
        vals = cost_data[bucket]
        print(table_row([bucket, len(vals), fmt_float(safe_mean(vals)), fmt_float(safe_median(vals))], widths))
        cost_analysis[bucket] = {"n": len(vals), "mean": safe_mean(vals), "median": safe_median(vals)}

    r_cost = pearson_r(cost_xs, cost_ys) if len(cost_xs) >= 3 else None
    print(f"\n  Pearson r (cost vs reward): {fmt_float(r_cost, 4)} (n={len(cost_xs)})")
    cost_analysis["pearson_r"] = r_cost
    cost_analysis["n_corr"] = len(cost_xs)
    report["section_4_multi_dimensional"]["cost_analysis"] = cost_analysis

    # 4h. Time analysis
    sub_header("4h. Wall Clock Time vs Reward")
    time_bins = [
        (0, 120, "<2m"),
        (120, 300, "2-5m"),
        (300, 600, "5-10m"),
        (600, 1200, "10-20m"),
        (1200, 1800, "20-30m"),
        (1800, float("inf"), ">30m"),
    ]
    time_data = defaultdict(list)
    time_xs, time_ys = [], []
    for tm in valid:
        t = tm.get("wall_clock_seconds")
        if t is not None and t > 0:
            bucket = bin_value(t, time_bins)
            time_data[bucket].append(tm["reward"])
            time_xs.append(t)
            time_ys.append(tm["reward"])

    widths = [-12, 5, 8, 8]
    print(table_row(["Time", "N", "Mean R", "Med R"], widths))
    print(table_row(["----", "--", "------", "-----"], widths))
    time_analysis = {}
    for bucket in ["<2m", "2-5m", "5-10m", "10-20m", "20-30m", ">30m"]:
        if bucket not in time_data:
            continue
        vals = time_data[bucket]
        print(table_row([bucket, len(vals), fmt_float(safe_mean(vals)), fmt_float(safe_median(vals))], widths))
        time_analysis[bucket] = {"n": len(vals), "mean": safe_mean(vals), "median": safe_median(vals)}

    r_time = pearson_r(time_xs, time_ys) if len(time_xs) >= 3 else None
    print(f"\n  Pearson r (time vs reward): {fmt_float(r_time, 4)} (n={len(time_xs)})")
    time_analysis["pearson_r"] = r_time
    time_analysis["n_corr"] = len(time_xs)
    report["section_4_multi_dimensional"]["time_analysis"] = time_analysis

    # 4i. Conversation turns vs reward
    sub_header("4i. Conversation Turns vs Reward")
    turns_bins = [
        (0, 5, "1-4"),
        (5, 10, "5-9"),
        (10, 20, "10-19"),
        (20, 50, "20-49"),
        (50, float("inf"), "50+"),
    ]
    turns_data = defaultdict(list)
    turns_xs, turns_ys = [], []
    for tm in valid:
        t = tm.get("conversation_turns")
        if t is not None and t > 0:
            bucket = bin_value(t, turns_bins)
            turns_data[bucket].append(tm["reward"])
            turns_xs.append(t)
            turns_ys.append(tm["reward"])

    widths = [-12, 5, 8, 8]
    print(table_row(["Turns", "N", "Mean R", "Med R"], widths))
    print(table_row(["-----", "--", "------", "-----"], widths))
    turns_analysis = {}
    for bucket in ["1-4", "5-9", "10-19", "20-49", "50+"]:
        if bucket not in turns_data:
            continue
        vals = turns_data[bucket]
        print(table_row([bucket, len(vals), fmt_float(safe_mean(vals)), fmt_float(safe_median(vals))], widths))
        turns_analysis[bucket] = {"n": len(vals), "mean": safe_mean(vals), "median": safe_median(vals)}

    r_turns = pearson_r(turns_xs, turns_ys) if len(turns_xs) >= 3 else None
    print(f"\n  Pearson r (turns vs reward): {fmt_float(r_turns, 4)} (n={len(turns_xs)})")
    turns_analysis["pearson_r"] = r_turns
    turns_analysis["n_corr"] = len(turns_xs)
    report["section_4_multi_dimensional"]["conversation_turns"] = turns_analysis

    # 4j. Search strategy across all configs
    sub_header("4j. Search Strategy Type vs Reward (All Configs)")
    strat_data = defaultdict(list)
    for tm in valid:
        strat = tm.get("search_strategy_type")
        if strat:
            strat_data[strat].append(tm["reward"])

    if strat_data:
        widths = [-25, 5, 8, 8]
        print(table_row(["Strategy", "N", "Mean R", "Med R"], widths))
        print(table_row(["--------", "--", "------", "-----"], widths))
        strat_all = {}
        for strat in sorted(strat_data.keys(), key=lambda s: -len(strat_data[s])):
            vals = strat_data[strat]
            print(table_row([strat, len(vals), fmt_float(safe_mean(vals)), fmt_float(safe_median(vals))], widths))
            strat_all[strat] = {"n": len(vals), "mean": safe_mean(vals), "median": safe_median(vals)}
        report["section_4_multi_dimensional"]["search_strategy_all"] = strat_all
    else:
        print("  No search strategy data.")
        report["section_4_multi_dimensional"]["search_strategy_all"] = {}

    # 4k. Feature correlations with reward
    sub_header("4k. Feature Correlations with Reward")
    features = {
        "input_tokens": [],
        "output_tokens": [],
        "tool_calls_total": [],
        "tool_calls_mcp": [],
        "tool_calls_local": [],
        "mcp_ratio": [],
        "files_modified": [],
        "lines_added": [],
        "lines_removed": [],
        "conversation_turns": [],
        "wall_clock_seconds": [],
        "cost_usd": [],
        "task_context_length": [],
        "task_files_count": [],
        "mcp_benefit_score": [],
        "instruction_length_chars": [],
        "cache_hit_rate": [],
        "context_window_peak_pct": [],
    }
    rewards_for_features = {k: [] for k in features}
    for tm in valid:
        r = tm["reward"]
        for feat in features:
            val = tm.get(feat)
            if val is not None and isinstance(val, (int, float)):
                features[feat].append(val)
                rewards_for_features[feat].append(r)

    widths = [-28, 6, 10]
    print(table_row(["Feature", "N", "Pearson r"], widths))
    print(table_row(["-------", "--", "---------"], widths))
    correlations = {}
    corr_list = []
    for feat in sorted(features.keys()):
        xs = features[feat]
        ys = rewards_for_features[feat]
        r = pearson_r(xs, ys)
        print(table_row([feat, len(xs), fmt_float(r, 4)], widths))
        correlations[feat] = {"n": len(xs), "pearson_r": r}
        if r is not None:
            corr_list.append((feat, r, len(xs)))

    # Rank by absolute correlation
    corr_list.sort(key=lambda x: abs(x[1]), reverse=True)
    print("\n  Ranked by |r|:")
    for i, (feat, r, n) in enumerate(corr_list[:10], 1):
        print(f"    {i:2d}. {feat:30s}  r={r:+.4f}  (n={n})")

    report["section_4_multi_dimensional"]["feature_correlations"] = correlations
    report["section_4_multi_dimensional"]["top_correlates"] = [
        {"feature": f, "pearson_r": r, "n": n} for f, r, n in corr_list[:10]
    ]


# ---------------------------------------------------------------------------
# Section 5: Key Findings Summary
# ---------------------------------------------------------------------------

def analyze_key_findings(task_metrics, retrieval_metrics, report):
    section_header("SECTION 5: Key Findings Summary")
    report["section_5_key_findings"] = {}

    paired = report.get("_paired_data", {})

    # 5a. Top 10 tasks where MCP helps most
    sub_header("5a. Top 10 Tasks Where MCP Helps Most")
    if paired:
        sorted_helps = sorted(paired.items(), key=lambda x: x[1]["delta"], reverse=True)
        widths = [-45, 8, 8, 9, -25]
        print(table_row(["Task ID", "BL", "MCP", "Delta", "Suite"], widths))
        print(table_row(["-------", "---", "---", "-----", "-----"], widths))
        top_helps = []
        for norm_id, p in sorted_helps[:10]:
            print(table_row([
                norm_id,
                fmt_float(p["baseline_reward"]),
                fmt_float(p["mcp_reward"]),
                f"{p['delta']:+.4f}",
                p.get("benchmark", ""),
            ], widths))
            top_helps.append({
                "task_id": norm_id,
                "baseline_reward": p["baseline_reward"],
                "mcp_reward": p["mcp_reward"],
                "delta": p["delta"],
                "suite": p.get("benchmark"),
            })
        report["section_5_key_findings"]["top_10_mcp_helps"] = top_helps
    else:
        print("  No paired data available.")
        report["section_5_key_findings"]["top_10_mcp_helps"] = []

    # 5b. Top 10 tasks where MCP hurts most
    sub_header("5b. Top 10 Tasks Where MCP Hurts Most")
    if paired:
        sorted_hurts = sorted(paired.items(), key=lambda x: x[1]["delta"])
        widths = [-45, 8, 8, 9, -25]
        print(table_row(["Task ID", "BL", "MCP", "Delta", "Suite"], widths))
        print(table_row(["-------", "---", "---", "-----", "-----"], widths))
        top_hurts = []
        for norm_id, p in sorted_hurts[:10]:
            print(table_row([
                norm_id,
                fmt_float(p["baseline_reward"]),
                fmt_float(p["mcp_reward"]),
                f"{p['delta']:+.4f}",
                p.get("benchmark", ""),
            ], widths))
            top_hurts.append({
                "task_id": norm_id,
                "baseline_reward": p["baseline_reward"],
                "mcp_reward": p["mcp_reward"],
                "delta": p["delta"],
                "suite": p.get("benchmark"),
            })
        report["section_5_key_findings"]["top_10_mcp_hurts"] = top_hurts
    else:
        print("  No paired data available.")
        report["section_5_key_findings"]["top_10_mcp_hurts"] = []

    # 5c. Tasks with best/worst IR metrics
    sub_header("5c. Top 10 Tasks by File Recall (Retrieval)")
    ir_tasks = []
    for rm in retrieval_metrics:
        flm = rm.get("file_level_metrics", {})
        if not flm or not flm.get("computable"):
            continue
        file_recall = flm.get("file_recall")
        mrr = flm.get("mrr")
        if file_recall is not None:
            ir_tasks.append({
                "task_id": rm["_normalized_task_id"],
                "config": rm["_config_name"],
                "file_recall": file_recall,
                "mrr": mrr,
                "n_gt": flm.get("n_ground_truth", 0),
                "n_overlap": flm.get("n_overlap", 0),
            })

    if ir_tasks:
        # Best
        ir_tasks_sorted = sorted(ir_tasks, key=lambda x: x["file_recall"], reverse=True)
        widths = [-40, -25, 10, 8, 6]
        print(table_row(["Task ID", "Config", "FileRecall", "MRR", "GT"], widths))
        print(table_row(["-------", "------", "----------", "---", "--"], widths))
        for t in ir_tasks_sorted[:10]:
            print(table_row([
                t["task_id"], t["config"],
                fmt_float(t["file_recall"]), fmt_float(t["mrr"]),
                t["n_gt"],
            ], widths))

        sub_header("5d. Bottom 10 Tasks by File Recall (Non-Zero GT)")
        # Worst (exclude those with 0 ground truth)
        ir_with_gt = [t for t in ir_tasks if t["n_gt"] > 0]
        ir_worst = sorted(ir_with_gt, key=lambda x: x["file_recall"])
        print(table_row(["Task ID", "Config", "FileRecall", "MRR", "GT"], widths))
        print(table_row(["-------", "------", "----------", "---", "--"], widths))
        for t in ir_worst[:10]:
            print(table_row([
                t["task_id"], t["config"],
                fmt_float(t["file_recall"]), fmt_float(t["mrr"]),
                t["n_gt"],
            ], widths))

        report["section_5_key_findings"]["top_10_ir_best"] = [
            {k: v for k, v in t.items()} for t in ir_tasks_sorted[:10]
        ]
        report["section_5_key_findings"]["top_10_ir_worst"] = [
            {k: v for k, v in t.items()} for t in ir_worst[:10]
        ]
    else:
        print("  No IR task data available.")
        report["section_5_key_findings"]["top_10_ir_best"] = []
        report["section_5_key_findings"]["top_10_ir_worst"] = []

    # 5e. Overall summary statistics
    sub_header("5e. Overall Summary Statistics")
    valid = [tm for tm in task_metrics if is_valid_for_analysis(tm)]
    all_rewards = [tm["reward"] for tm in valid if tm.get("reward") is not None]
    bl_rewards = [tm["reward"] for tm in valid if tm["_config_type"] == "baseline" and tm.get("reward") is not None]
    mcp_rewards = [tm["reward"] for tm in valid if tm["_config_type"] == "mcp" and tm.get("reward") is not None]

    print(f"  Total valid task records:     {len(valid)}")
    print(f"  Unique normalized task IDs:   {len(set(tm['_normalized_task_id'] for tm in valid))}")
    print(f"  Overall mean reward:          {fmt_float(safe_mean(all_rewards))}")
    print(f"  Baseline mean reward:         {fmt_float(safe_mean(bl_rewards))} (n={len(bl_rewards)})")
    print(f"  MCP mean reward:              {fmt_float(safe_mean(mcp_rewards))} (n={len(mcp_rewards)})")
    if paired:
        deltas = [p["delta"] for p in paired.values()]
        print(f"  Paired tasks:                 {len(paired)}")
        print(f"  Mean MCP delta:               {safe_mean(deltas):+.4f}")
        helps = sum(1 for d in deltas if d > DELTA_THRESHOLD)
        hurts = sum(1 for d in deltas if d < -DELTA_THRESHOLD)
        print(f"  MCP helps / hurts / neutral:  {helps} / {hurts} / {len(paired) - helps - hurts}")

    # Token/cost summary
    costs = [tm.get("cost_usd") for tm in valid if tm.get("cost_usd") is not None and tm.get("cost_usd") > 0]
    tokens_in = [tm.get("input_tokens") for tm in valid if tm.get("input_tokens")]
    tokens_out = [tm.get("output_tokens") for tm in valid if tm.get("output_tokens")]
    print(f"\n  Cost: mean=${fmt_float(safe_mean(costs), 4)}, "
          f"median=${fmt_float(safe_median(costs), 4)}, "
          f"total=${fmt_float(sum(costs), 2) if costs else 'N/A'} (n={len(costs)})")
    print(f"  Input tokens: mean={fmt_int(int(safe_mean(tokens_in))) if tokens_in else 'N/A'}, "
          f"total={fmt_int(sum(tokens_in)) if tokens_in else 'N/A'}")
    print(f"  Output tokens: mean={fmt_int(int(safe_mean(tokens_out))) if tokens_out else 'N/A'}, "
          f"total={fmt_int(sum(tokens_out)) if tokens_out else 'N/A'}")

    report["section_5_key_findings"]["summary"] = {
        "total_valid_records": len(valid),
        "unique_tasks": len(set(tm["_normalized_task_id"] for tm in valid)),
        "overall_mean_reward": safe_mean(all_rewards),
        "baseline_mean_reward": safe_mean(bl_rewards),
        "mcp_mean_reward": safe_mean(mcp_rewards),
        "n_baseline": len(bl_rewards),
        "n_mcp": len(mcp_rewards),
        "n_paired": len(paired),
        "mean_cost_usd": safe_mean(costs),
        "total_cost_usd": sum(costs) if costs else None,
        "total_input_tokens": sum(tokens_in) if tokens_in else None,
        "total_output_tokens": sum(tokens_out) if tokens_out else None,
    }

    # 5f. Strongest feature-reward correlations summary
    sub_header("5f. Strongest Correlates with Reward (from Section 4)")
    top_corr = report.get("section_4_multi_dimensional", {}).get("top_correlates", [])
    if top_corr:
        widths = [-30, 10, 6]
        print(table_row(["Feature", "Pearson r", "N"], widths))
        print(table_row(["-------", "---------", "--"], widths))
        for entry in top_corr:
            print(table_row([
                entry["feature"],
                fmt_float(entry["pearson_r"], 4),
                entry["n"],
            ], widths))
    else:
        print("  No correlation data available.")
    report["section_5_key_findings"]["top_correlates"] = top_corr


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * SECTION_WIDTH)
    print("  CodeScaleBench Comprehensive Analysis Report")
    print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * SECTION_WIDTH)

    # Load data
    print("\n  Loading data sources...")

    manifest_runs = load_manifest()
    print(f"    MANIFEST.json:               {len(manifest_runs)} runs")

    raw_task_metrics = load_task_metrics()
    print(f"    task_metrics.json files:      {len(raw_task_metrics)} records found")

    task_metrics = deduplicate_task_metrics(raw_task_metrics)
    print(f"    After deduplication:          {len(task_metrics)} records")

    retrieval_metrics = load_retrieval_metrics()
    print(f"    retrieval_metrics.json files: {len(retrieval_metrics)} records found")

    selected_tasks = load_selected_tasks()
    print(f"    selected_benchmark_tasks:     {len(selected_tasks)} tasks")

    agg_retrieval = load_aggregate_retrieval()
    print(f"    Aggregate retrieval summary:  {'loaded' if agg_retrieval else 'not found'}")

    # Enrich task metrics with selected task metadata
    enrich_task_metrics(task_metrics, selected_tasks)

    # Report container
    report = {
        "meta": {
            "generated": datetime.now().isoformat(),
            "manifest_runs": len(manifest_runs),
            "task_metrics_raw": len(raw_task_metrics),
            "task_metrics_deduped": len(task_metrics),
            "retrieval_metrics": len(retrieval_metrics),
            "selected_tasks": len(selected_tasks),
        },
    }

    # Run analyses
    analyze_score_distribution(task_metrics, manifest_runs, report)
    analyze_mcp_impact(task_metrics, selected_tasks, report)
    analyze_ir_retrieval(retrieval_metrics, task_metrics, report)
    analyze_multi_dimensional(task_metrics, report)
    analyze_key_findings(task_metrics, retrieval_metrics, report)

    # Clean internal keys before writing JSON
    if "_paired_data" in report:
        del report["_paired_data"]

    # Write JSON report
    OUTPUT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON_PATH, "w") as f:
        json.dump(report, f, indent=2, default=str)

    section_header("OUTPUT")
    print(f"  JSON report written to: {OUTPUT_JSON_PATH}")
    print(f"  Report size: {os.path.getsize(OUTPUT_JSON_PATH):,} bytes")
    print()


if __name__ == "__main__":
    main()
