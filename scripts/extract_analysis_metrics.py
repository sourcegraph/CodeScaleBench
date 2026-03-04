#!/usr/bin/env python3
"""Extract and analyze benchmark metrics across multiple dimensions.

Joins run results with task metadata to produce analysis tables and
exportable data for:
  - Efficiency metrics (agent task time, tokens) by config
  - Outcomes by difficulty/complexity
  - Outcomes by codebase size (MCP benefit score components)
  - Outcomes by task type (category, SDLC phase)
  - Outcomes by coding language
  - Per-task detail export (CSV/JSON)

Usage:
    # Print all analysis tables
    python3 scripts/extract_analysis_metrics.py

    # Export per-task CSV for external analysis
    python3 scripts/extract_analysis_metrics.py --export-csv analysis.csv

    # Export per-task JSON
    python3 scripts/extract_analysis_metrics.py --export-json analysis.json

    # Filter by suite or config
    python3 scripts/extract_analysis_metrics.py --suite ccb_pytorch
    python3 scripts/extract_analysis_metrics.py --config baseline

    # Show specific dimension only
    python3 scripts/extract_analysis_metrics.py --dimension language
    python3 scripts/extract_analysis_metrics.py --dimension difficulty
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from config_utils import discover_configs, config_short_name

RUNS_DIR = PROJECT_ROOT / "runs" / "official"
SELECTED_TASKS_PATH = PROJECT_ROOT / "configs" / "selected_benchmark_tasks.json"

SKIP_PATTERNS = ["__broken_verifier", "validation_test", "archive"]

DIR_PREFIX_TO_SUITE = {
    "bigcode_mcp_": "ccb_largerepo",
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
}

CONFIG_SHORT = {
    "baseline": "BL",
    "sourcegraph_full": "SG_full",
}

DIMENSIONS = [
    "summary",
    "benchmark",
    "difficulty",
    "language",
    "category",
    "sdlc_phase",
    "complexity",
    "mcp_benefit",
    "repo",
]


# ---------------------------------------------------------------------------
# Task metadata loading
# ---------------------------------------------------------------------------

def load_task_metadata() -> dict[str, dict]:
    """Load selected_benchmark_tasks.json and index by task_id.

    Returns dict mapping task_id -> metadata dict with fields:
      benchmark, sdlc_phase, language, difficulty, category, repo,
      mcp_benefit_score, mcp_breakdown, task_dir
    """
    if not SELECTED_TASKS_PATH.is_file():
        print(f"WARNING: {SELECTED_TASKS_PATH} not found", file=sys.stderr)
        return {}

    data = json.loads(SELECTED_TASKS_PATH.read_text())
    tasks_list = data.get("tasks", data) if isinstance(data, dict) else data

    index = {}
    for t in tasks_list:
        task_id = t.get("task_id", "")
        if task_id:
            index[task_id] = {
                "benchmark": t.get("benchmark", ""),
                "sdlc_phase": t.get("sdlc_phase", ""),
                "language": t.get("language", ""),
                "difficulty": t.get("difficulty", ""),
                "category": t.get("category", ""),
                "repo": t.get("repo", ""),
                "mcp_benefit_score": t.get("mcp_benefit_score", 0.0),
                "mcp_breakdown": t.get("mcp_breakdown", {}),
                "task_dir": t.get("task_dir", ""),
            }
    return index


# ---------------------------------------------------------------------------
# Result scanning (reuses patterns from generate_manifest.py)
# ---------------------------------------------------------------------------

def should_skip(dirname: str) -> bool:
    return any(pat in dirname for pat in SKIP_PATTERNS)


def detect_suite(dirname: str) -> Optional[str]:
    for prefix, suite in DIR_PREFIX_TO_SUITE.items():
        if dirname.startswith(prefix):
            return suite
    return None


def _normalize_task_name(name: str) -> str:
    """Normalize SWE-bench Pro task names (dash vs double-underscore)."""
    if not name.startswith("instance_"):
        return name
    if "__" in name[len("instance_"):]:
        return name
    suffix = name[len("instance_"):]
    dash_pos = suffix.find("-")
    if dash_pos > 0:
        return "instance_" + suffix[:dash_pos] + "__" + suffix[dash_pos + 1:]
    return name


def parse_iso_ts(ts_str: str) -> Optional[datetime]:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def wall_clock_seconds(started: str, finished: str) -> Optional[float]:
    s = parse_iso_ts(started)
    f = parse_iso_ts(finished)
    if s and f:
        return (f - s).total_seconds()
    return None


def extract_result(result_path: Path) -> Optional[dict]:
    """Extract metrics from a task-level result.json."""
    try:
        data = json.loads(result_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    # Skip batch-level result.json
    if "task_name" not in data and "trial_name" not in data:
        return None

    task_name = data.get("task_name", "")
    if not task_name:
        parts = result_path.parent.name.rsplit("__", 1)
        task_name = parts[0] if len(parts) == 2 else result_path.parent.name

    # Reward
    verifier = data.get("verifier_result") or {}
    rewards = verifier.get("rewards") or {}
    reward = rewards.get("reward")
    if reward is None:
        reward = rewards.get("score")

    # Status
    exception = data.get("exception_info")
    agent_result = data.get("agent_result") or {}
    n_input = agent_result.get("n_input_tokens") or 0
    n_output = agent_result.get("n_output_tokens") or 0
    zero_token = (n_input == 0 and n_output == 0)

    if exception is not None:
        status = "errored"
        reward_val = 0.0
    elif zero_token:
        status = "errored"
        reward_val = 0.0
    elif reward is not None and reward > 0:
        status = "passed"
        reward_val = float(reward)
    else:
        status = "failed"
        reward_val = float(reward) if reward is not None else 0.0

    # Tokens
    n_input_tokens = agent_result.get("n_input_tokens")
    n_output_tokens = agent_result.get("n_output_tokens")
    n_cache_tokens = agent_result.get("n_cache_tokens",
                     agent_result.get("cache_creation_input_tokens"))
    cache_read = agent_result.get("cache_read_input_tokens")
    total_cost = agent_result.get("total_cost_usd")

    # Timing
    started_at = data.get("started_at", "")
    finished_at = data.get("finished_at", "")
    wc = wall_clock_seconds(started_at, finished_at)

    agent_exec = data.get("agent_execution") or {}
    agent_task_secs = wall_clock_seconds(
        agent_exec.get("started_at", ""),
        agent_exec.get("finished_at", ""),
    )

    env_setup = data.get("environment_setup") or {}
    env_setup_secs = wall_clock_seconds(
        env_setup.get("started_at", ""),
        env_setup.get("finished_at", ""),
    )

    return {
        "task_name": _normalize_task_name(task_name),
        "status": status,
        "reward": round(reward_val, 4),
        "n_input_tokens": n_input_tokens,
        "n_output_tokens": n_output_tokens,
        "n_cache_tokens": n_cache_tokens,
        "cache_read_tokens": cache_read,
        "total_cost_usd": total_cost,
        "wall_clock_seconds": round(wc, 1) if wc else None,
        "agent_task_seconds": round(agent_task_secs, 1) if agent_task_secs else None,
        "env_setup_seconds": round(env_setup_secs, 1) if env_setup_secs else None,
        "started_at": started_at,
    }


def _has_agent_output(data: dict) -> bool:
    ar = data.get("agent_result") or {}
    return (ar.get("n_input_tokens") or 0) > 0 or (ar.get("n_output_tokens") or 0) > 0


def load_selected_task_names() -> dict[str, set[str]]:
    """Load selected task names indexed by suite for filtering.

    Returns {suite: {task_name, ...}} with both normalized forms.
    """
    if not SELECTED_TASKS_PATH.is_file():
        return {}
    data = json.loads(SELECTED_TASKS_PATH.read_text())
    tasks_list = data.get("tasks", data) if isinstance(data, dict) else data
    result: dict[str, set[str]] = defaultdict(set)
    for t in tasks_list:
        suite = t.get("benchmark", "")
        if not suite.startswith(("ccb_", "csb_")):
            suite = "csb_sdlc_" + suite
        task_id = t.get("task_id", "")
        if suite and task_id:
            normalized = _normalize_task_name(task_id)
            result[suite].add(normalized)
            if normalized.startswith(("ccb_", "csb_")):
                result[suite].add(normalized[4:])
            if not normalized.startswith(("ccb_", "csb_")):
                result[suite].add("csb_sdlc_" + normalized)
                result[suite].add("ccb_" + normalized)
    return dict(result)


def collect_results(
    suite_filter: Optional[str] = None,
    config_filter: Optional[str] = None,
    selected_only: bool = True,
) -> list[dict]:
    """Scan runs/official/ and return deduplicated per-task records.

    Each record has: suite, config, task_name, + all extract_result fields.
    If selected_only=True, filters to tasks in selected_benchmark_tasks.json.
    """
    best: dict[tuple[str, str, str], dict] = {}

    if not RUNS_DIR.exists():
        print(f"ERROR: {RUNS_DIR} not found", file=sys.stderr)
        return []

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir() or should_skip(run_dir.name):
            continue

        suite = detect_suite(run_dir.name)
        if suite is None:
            continue
        if suite_filter and suite != suite_filter:
            continue

        for config in discover_configs(run_dir):
            if config_filter and config != config_filter:
                continue

            config_path = run_dir / config

            for entry in sorted(config_path.iterdir()):
                if not entry.is_dir() or should_skip(entry.name):
                    continue

                # Handle both layouts
                task_dirs = []
                if entry.name.startswith("20"):
                    # Timestamp batch dir
                    for trial in sorted(entry.iterdir()):
                        if trial.is_dir() and not trial.name.startswith("20") and not should_skip(trial.name):
                            task_dirs.append(trial)
                elif "__" in entry.name:
                    task_dirs.append(entry)

                for task_dir in task_dirs:
                    result_path = task_dir / "result.json"
                    if not result_path.is_file():
                        continue

                    info = extract_result(result_path)
                    if info is None:
                        continue

                    record = {"suite": suite, "config": config, **info}
                    key = (suite, config, info["task_name"])

                    existing = best.get(key)
                    if existing is None:
                        best[key] = record
                    else:
                        # Prefer records with agent output; tie-break by timestamp
                        new_has = (info.get("n_input_tokens") or 0) > 0
                        old_has = (existing.get("n_input_tokens") or 0) > 0
                        if new_has and not old_has:
                            best[key] = record
                        elif not new_has and old_has:
                            pass
                        elif info["started_at"] >= existing["started_at"]:
                            best[key] = record

    records = sorted(best.values(), key=lambda r: (r["suite"], r["config"], r["task_name"]))

    # Filter to selected tasks only
    if selected_only:
        selected = load_selected_task_names()
        if selected:
            before = len(records)
            filtered = []
            for r in records:
                allowed = selected.get(r["suite"])
                if allowed is None:
                    filtered.append(r)  # Suite not in selection — keep
                elif _normalize_task_name(r["task_name"]) in allowed:
                    filtered.append(r)
            removed = before - len(filtered)
            if removed:
                print(f"  Filtered out {removed} tasks not in selection registry", file=sys.stderr)
            records = filtered

    return records


# ---------------------------------------------------------------------------
# Join results with metadata
# ---------------------------------------------------------------------------

def join_with_metadata(results: list[dict], metadata: dict[str, dict]) -> list[dict]:
    """Enrich each result record with task metadata fields."""
    enriched = []
    unmatched = 0

    for r in results:
        task_name = r["task_name"]
        meta = metadata.get(task_name)

        if meta is None:
            # Try without ccb_ prefix
            for prefix in ("ccb_", ""):
                alt = prefix + task_name if prefix else task_name.replace("ccb_", "", 1)
                meta = metadata.get(alt)
                if meta:
                    break

        if meta:
            r["language"] = meta.get("language", "unknown")
            r["difficulty"] = meta.get("difficulty", "unknown")
            r["category"] = meta.get("category", "unknown")
            r["sdlc_phase"] = meta.get("sdlc_phase", "unknown")
            r["repo"] = meta.get("repo", "unknown")
            r["mcp_benefit_score"] = meta.get("mcp_benefit_score", 0.0)
            r["mcp_breakdown"] = meta.get("mcp_breakdown", {})
            r["context_complexity"] = meta.get("mcp_breakdown", {}).get("context_complexity", 0.0)
            r["cross_file_deps"] = meta.get("mcp_breakdown", {}).get("cross_file_deps", 0.0)
        else:
            unmatched += 1
            r["language"] = "unknown"
            r["difficulty"] = "unknown"
            r["category"] = "unknown"
            r["sdlc_phase"] = "unknown"
            r["repo"] = "unknown"
            r["mcp_benefit_score"] = 0.0
            r["mcp_breakdown"] = {}
            r["context_complexity"] = 0.0
            r["cross_file_deps"] = 0.0

        enriched.append(r)

    if unmatched > 0:
        print(f"  NOTE: {unmatched} tasks had no metadata match", file=sys.stderr)

    return enriched


# ---------------------------------------------------------------------------
# Aggregation engine
# ---------------------------------------------------------------------------

class MetricsBucket:
    """Accumulates metrics for a group of tasks."""

    def __init__(self):
        self.count = 0
        self.passed = 0
        self.failed = 0
        self.errored = 0
        self.total_reward = 0.0
        self.scored = 0  # non-errored
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_task_seconds = 0.0
        self.timed_count = 0
        self.total_wall_seconds = 0.0
        self.wall_count = 0
        self.rewards = []

    def add(self, record: dict):
        self.count += 1
        status = record["status"]
        if status == "passed":
            self.passed += 1
        elif status == "errored":
            self.errored += 1
        else:
            self.failed += 1

        if status != "errored":
            self.scored += 1
            self.total_reward += record["reward"]
            self.rewards.append(record["reward"])

        if record.get("n_input_tokens") is not None:
            self.total_input_tokens += record["n_input_tokens"]
        if record.get("n_output_tokens") is not None:
            self.total_output_tokens += record["n_output_tokens"]
        if record.get("agent_task_seconds") is not None:
            self.total_task_seconds += record["agent_task_seconds"]
            self.timed_count += 1
        if record.get("wall_clock_seconds") is not None:
            self.total_wall_seconds += record["wall_clock_seconds"]
            self.wall_count += 1

    def summary(self) -> dict:
        mean_reward = round(self.total_reward / self.scored, 4) if self.scored > 0 else 0.0
        pass_rate = round(self.passed / self.scored, 4) if self.scored > 0 else 0.0
        avg_task_s = round(self.total_task_seconds / self.timed_count, 1) if self.timed_count > 0 else None
        avg_wall_s = round(self.total_wall_seconds / self.wall_count, 1) if self.wall_count > 0 else None
        avg_input = round(self.total_input_tokens / self.count) if self.count > 0 else 0
        avg_output = round(self.total_output_tokens / self.count) if self.count > 0 else 0

        # Median reward
        median_reward = None
        if self.rewards:
            s = sorted(self.rewards)
            mid = len(s) // 2
            median_reward = round(s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2, 4)

        return {
            "n": self.count,
            "passed": self.passed,
            "failed": self.failed,
            "errored": self.errored,
            "pass_rate": pass_rate,
            "mean_reward": mean_reward,
            "median_reward": median_reward,
            "avg_task_seconds": avg_task_s,
            "avg_wall_seconds": avg_wall_s,
            "avg_input_tokens": avg_input,
            "avg_output_tokens": avg_output,
            "total_task_seconds": round(self.total_task_seconds, 1),
            "total_input_tokens": self.total_input_tokens,
        }


def aggregate_by_dimension(
    records: list[dict],
    dim_field: str,
    config_field: str = "config",
) -> dict[str, dict[str, dict]]:
    """Group records by (dim_field, config) and compute aggregated metrics.

    Returns: {dim_value: {config: summary_dict}}
    """
    buckets: dict[tuple[str, str], MetricsBucket] = defaultdict(MetricsBucket)

    for r in records:
        dim_val = str(r.get(dim_field, "unknown"))
        cfg = r[config_field]
        buckets[(dim_val, cfg)].add(r)

    # Restructure
    result: dict[str, dict[str, dict]] = defaultdict(dict)
    for (dim_val, cfg), bucket in sorted(buckets.items()):
        result[dim_val][cfg] = bucket.summary()

    return dict(result)


def aggregate_by_mcp_benefit_bin(
    records: list[dict],
) -> dict[str, dict[str, dict]]:
    """Bin records by MCP benefit score ranges and aggregate."""
    def bin_score(score: float) -> str:
        if score < 0.3:
            return "low (<0.3)"
        elif score < 0.6:
            return "medium (0.3-0.6)"
        elif score < 0.8:
            return "high (0.6-0.8)"
        else:
            return "very_high (>=0.8)"

    buckets: dict[tuple[str, str], MetricsBucket] = defaultdict(MetricsBucket)
    for r in records:
        bin_label = bin_score(r.get("mcp_benefit_score", 0.0))
        cfg = r["config"]
        buckets[(bin_label, cfg)].add(r)

    result: dict[str, dict[str, dict]] = defaultdict(dict)
    for (bin_label, cfg), bucket in sorted(buckets.items()):
        result[bin_label][cfg] = bucket.summary()
    return dict(result)


def aggregate_by_complexity_bin(
    records: list[dict],
) -> dict[str, dict[str, dict]]:
    """Bin records by context_complexity (codebase size proxy) and aggregate."""
    def bin_complexity(cc: float) -> str:
        if cc < 0.3:
            return "small (<0.3)"
        elif cc < 0.6:
            return "medium (0.3-0.6)"
        elif cc < 0.8:
            return "large (0.6-0.8)"
        else:
            return "very_large (>=0.8)"

    buckets: dict[tuple[str, str], MetricsBucket] = defaultdict(MetricsBucket)
    for r in records:
        bin_label = bin_complexity(r.get("context_complexity", 0.0))
        cfg = r["config"]
        buckets[(bin_label, cfg)].add(r)

    result: dict[str, dict[str, dict]] = defaultdict(dict)
    for (bin_label, cfg), bucket in sorted(buckets.items()):
        result[bin_label][cfg] = bucket.summary()
    return dict(result)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_table(
    title: str,
    data: dict[str, dict[str, dict]],
    metric_cols: list[tuple[str, str, int]] | None = None,
) -> str:
    """Format an aggregation result as a text table.

    metric_cols: list of (field_name, header, width) to display per config.
    """
    if metric_cols is None:
        metric_cols = [
            ("n", "N", 5),
            ("pass_rate", "Pass%", 6),
            ("mean_reward", "Reward", 7),
            ("avg_task_seconds", "TaskS", 7),
            ("avg_input_tokens", "AvgIn", 9),
            ("avg_output_tokens", "AvgOut", 8),
        ]

    lines = []
    lines.append(f"\n{'=' * 100}")
    lines.append(f"  {title}")
    lines.append(f"{'=' * 100}")

    # Header row
    dim_width = max(25, max((len(str(k)) for k in data.keys()), default=25) + 2)
    _all_cfgs = sorted({cfg for dim_data in data.values() for cfg in dim_data})
    header = f"  {'Dimension':<{dim_width}}"
    for cfg in _all_cfgs:
        short = CONFIG_SHORT.get(cfg, config_short_name(cfg))
        sub_header = " | ".join(f"{h:>{w}}" for _, h, w in metric_cols)
        header += f"  {short}: {sub_header}"
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))

    # Data rows
    for dim_val in sorted(data.keys()):
        configs = data[dim_val]
        row = f"  {dim_val:<{dim_width}}"
        for cfg in _all_cfgs:
            s = configs.get(cfg)
            if s:
                cells = []
                for field, _, w in metric_cols:
                    val = s.get(field)
                    if val is None:
                        cells.append(f"{'N/A':>{w}}")
                    elif isinstance(val, float):
                        if field == "pass_rate":
                            cells.append(f"{val * 100:>{w}.1f}")
                        else:
                            cells.append(f"{val:>{w}.1f}" if val >= 10 else f"{val:>{w}.3f}")
                    elif isinstance(val, int):
                        cells.append(f"{val:>{w},}")
                    else:
                        cells.append(f"{val:>{w}}")
                row += "  " + " | ".join(cells)
            else:
                row += "  " + " | ".join(f"{'-':>{w}}" for _, _, w in metric_cols)
        lines.append(row)

    return "\n".join(lines)


def format_delta_table(
    title: str,
    data: dict[str, dict[str, dict]],
    base_config: str = "baseline",
    compare_configs: list[str] | None = None,
) -> str:
    """Format a table showing deltas from baseline for key metrics."""
    if compare_configs is None:
        compare_configs = ["sourcegraph_full"]

    lines = []
    lines.append(f"\n{'=' * 90}")
    lines.append(f"  {title} (delta from baseline)")
    lines.append(f"{'=' * 90}")

    metrics = [
        ("mean_reward", "Reward", "+.3f"),
        ("pass_rate", "Pass%", "+.1f"),
        ("avg_task_seconds", "TaskS", "+.0f"),
    ]

    dim_width = max(25, max((len(str(k)) for k in data.keys()), default=25) + 2)
    header = f"  {'Dimension':<{dim_width}}  {'BL_Reward':>9}"
    for cfg in compare_configs:
        short = CONFIG_SHORT[cfg]
        for _, mh, _ in metrics:
            header += f"  {short}_{mh}:>10"
    # Simplified header
    header = f"  {'Dimension':<{dim_width}}"
    for cfg in compare_configs:
        short = CONFIG_SHORT[cfg]
        header += f"  {short+'_dReward':>14}  {short+'_dPass%':>13}  {short+'_dTaskS':>13}"
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))

    for dim_val in sorted(data.keys()):
        configs = data[dim_val]
        base = configs.get(base_config)
        if not base:
            continue

        row = f"  {dim_val:<{dim_width}}"
        for cfg in compare_configs:
            comp = configs.get(cfg)
            if not comp:
                row += f"  {'N/A':>14}  {'N/A':>13}  {'N/A':>13}"
                continue

            dr = (comp["mean_reward"] - base["mean_reward"])
            dp = ((comp["pass_rate"] - base["pass_rate"]) * 100)
            dt_base = base.get("avg_task_seconds")
            dt_comp = comp.get("avg_task_seconds")
            if dt_base and dt_comp:
                dt = dt_comp - dt_base
                dt_str = f"{dt:>+13.0f}"
            else:
                dt_str = f"{'N/A':>13}"

            row += f"  {dr:>+14.3f}  {dp:>+13.1f}  {dt_str}"
        lines.append(row)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CSV/JSON export
# ---------------------------------------------------------------------------

EXPORT_FIELDS = [
    "suite", "config", "task_name", "status", "reward",
    "language", "difficulty", "category", "sdlc_phase", "repo",
    "mcp_benefit_score", "context_complexity", "cross_file_deps",
    "n_input_tokens", "n_output_tokens", "n_cache_tokens",
    "cache_read_tokens", "total_cost_usd",
    "agent_task_seconds", "wall_clock_seconds", "env_setup_seconds",
]


def export_csv(records: list[dict], path: str):
    """Export enriched records to CSV."""
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in records:
            writer.writerow({k: r.get(k, "") for k in EXPORT_FIELDS})
    print(f"Exported {len(records)} records to {path}", file=sys.stderr)


def export_json(records: list[dict], path: str):
    """Export enriched records to JSON."""
    # Strip non-serializable fields
    clean = []
    for r in records:
        row = {k: r.get(k) for k in EXPORT_FIELDS}
        clean.append(row)

    with open(path, "w") as f:
        json.dump({"records": clean, "count": len(clean)}, f, indent=2)
    print(f"Exported {len(records)} records to {path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Extract and analyze benchmark metrics across multiple dimensions."
    )
    parser.add_argument("--suite", default=None, help="Filter by benchmark suite")
    parser.add_argument("--config", default=None, help="Filter by config")
    parser.add_argument("--dimension", default=None, choices=DIMENSIONS,
                        help="Show only one dimension")
    parser.add_argument("--export-csv", default=None, metavar="PATH",
                        help="Export per-task records to CSV")
    parser.add_argument("--export-json", default=None, metavar="PATH",
                        help="Export per-task records to JSON")
    parser.add_argument("--deltas", action="store_true",
                        help="Show delta tables (improvement over baseline)")
    parser.add_argument("--no-selected-filter", action="store_true",
                        help="Include all tasks, not just those in selection registry")
    args = parser.parse_args()

    # 1. Load task metadata
    print("Loading task metadata...", file=sys.stderr)
    metadata = load_task_metadata()
    print(f"  {len(metadata)} tasks in selection registry", file=sys.stderr)

    # 2. Scan results
    print("Scanning run results...", file=sys.stderr)
    results = collect_results(
        suite_filter=args.suite,
        config_filter=args.config,
        selected_only=not args.no_selected_filter,
    )
    print(f"  {len(results)} task results found", file=sys.stderr)

    # 3. Join
    print("Joining results with metadata...", file=sys.stderr)
    enriched = join_with_metadata(results, metadata)

    # 4. Export if requested
    if args.export_csv:
        export_csv(enriched, args.export_csv)
    if args.export_json:
        export_json(enriched, args.export_json)

    # 5. Analysis tables
    dim = args.dimension
    output_parts = []

    output_parts.append(f"\nCodeScaleBench Analysis Report")
    output_parts.append(f"Generated: {datetime.utcnow().isoformat()}")
    output_parts.append(f"Total records: {len(enriched)}")
    config_counts = defaultdict(int)
    for r in enriched:
        config_counts[r["config"]] += 1
    for cfg in sorted(config_counts.keys()):
        output_parts.append(f"  {CONFIG_SHORT.get(cfg, config_short_name(cfg))}: {config_counts.get(cfg, 0)} tasks")

    # Summary (overall)
    if dim is None or dim == "summary":
        overall = aggregate_by_dimension(enriched, "suite")
        output_parts.append(format_table("OUTCOMES BY BENCHMARK SUITE", overall))

    # By benchmark
    if dim is None or dim == "benchmark":
        by_bench = aggregate_by_dimension(enriched, "suite")
        if args.deltas:
            output_parts.append(format_delta_table("BENCHMARK SUITE DELTAS", by_bench))

    # By difficulty
    if dim is None or dim == "difficulty":
        by_diff = aggregate_by_dimension(enriched, "difficulty")
        output_parts.append(format_table("OUTCOMES BY DIFFICULTY", by_diff))
        if args.deltas:
            output_parts.append(format_delta_table("DIFFICULTY DELTAS", by_diff))

    # By language
    if dim is None or dim == "language":
        by_lang = aggregate_by_dimension(enriched, "language")
        output_parts.append(format_table("OUTCOMES BY LANGUAGE", by_lang))
        if args.deltas:
            output_parts.append(format_delta_table("LANGUAGE DELTAS", by_lang))

    # By category
    if dim is None or dim == "category":
        by_cat = aggregate_by_dimension(enriched, "category")
        output_parts.append(format_table("OUTCOMES BY TASK CATEGORY", by_cat))
        if args.deltas:
            output_parts.append(format_delta_table("CATEGORY DELTAS", by_cat))

    # By SDLC phase
    if dim is None or dim == "sdlc_phase":
        by_sdlc = aggregate_by_dimension(enriched, "sdlc_phase")
        output_parts.append(format_table("OUTCOMES BY SDLC PHASE", by_sdlc))
        if args.deltas:
            output_parts.append(format_delta_table("SDLC PHASE DELTAS", by_sdlc))

    # By complexity (codebase size proxy)
    if dim is None or dim == "complexity":
        by_complexity = aggregate_by_complexity_bin(enriched)
        output_parts.append(format_table("OUTCOMES BY CODEBASE SIZE (context_complexity)", by_complexity))
        if args.deltas:
            output_parts.append(format_delta_table("CODEBASE SIZE DELTAS", by_complexity))

    # By MCP benefit score
    if dim is None or dim == "mcp_benefit":
        by_mcp = aggregate_by_mcp_benefit_bin(enriched)
        output_parts.append(format_table("OUTCOMES BY MCP BENEFIT SCORE", by_mcp))
        if args.deltas:
            output_parts.append(format_delta_table("MCP BENEFIT DELTAS", by_mcp))

    # By repo (top repos only)
    if dim == "repo":
        by_repo = aggregate_by_dimension(enriched, "repo")
        output_parts.append(format_table("OUTCOMES BY REPOSITORY", by_repo))

    print("\n".join(output_parts))


if __name__ == "__main__":
    main()
