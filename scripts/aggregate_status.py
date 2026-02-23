#!/usr/bin/env python3
"""Aggregate benchmark run status scanner.

Scans runs/official/ for task directories, classifies each task's status,
fingerprints errors, and produces structured summaries.

Usage:
    # JSON output (default)
    python3 scripts/aggregate_status.py

    # Compact table
    python3 scripts/aggregate_status.py --format table

    # Only failures
    python3 scripts/aggregate_status.py --failures-only --format table

    # Filter by suite or config
    python3 scripts/aggregate_status.py --suite ccb_pytorch --config baseline

    # Continuous watch mode
    python3 scripts/aggregate_status.py --format table --watch --interval 30

    # Write per-task status.json files
    python3 scripts/aggregate_status.py --write-status
"""

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# Ensure scripts/ is on path for sibling imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from status_fingerprints import fingerprint_error
from config_utils import discover_configs, is_mcp_config, config_short_name

# ---------------------------------------------------------------------------
# Constants (duplicated from generate_manifest.py for independence)
# ---------------------------------------------------------------------------

RUNS_DIR_OFFICIAL = Path(__file__).resolve().parent.parent / "runs" / "official"
RUNS_DIR_STAGING = Path(__file__).resolve().parent.parent / "runs" / "staging"
RUNS_DIR = RUNS_DIR_OFFICIAL  # default; overridden by --staging flag

# __v1_hinted: old run dirs from before enterprise task de-hinting (US-001..US-003).
# Appended to batch dir names after reruns complete so pre-redesign data is excluded.
SKIP_PATTERNS = ["__broken_verifier", "validation_test", "archive", "__v1_hinted", "__aborted"]

DIR_PREFIX_TO_SUITE = {
    # SDLC phase suite prefixes (new naming: {phase}_{model}_{timestamp})
    "build_": "ccb_build",
    "debug_": "ccb_debug",
    "design_": "ccb_design",
    "document_": "ccb_document",
    "fix_": "ccb_fix",
    "secure_": "ccb_secure",
    "test_": "ccb_test",
    "understand_": "ccb_understand",
    # Legacy benchmark prefixes
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
    "navprove_": "ccb_navprove",
    "nlqa_": "ccb_nlqa",
    "onboarding_": "ccb_onboarding",
    "pytorch_": "ccb_pytorch",
    "repoqa_": "ccb_repoqa",
    "security_": "ccb_security",
    "swebenchpro_": "ccb_swebenchpro",
    "sweperf_": "ccb_sweperf",
    "tac_": "ccb_tac",
    # MCP-unique org-scale retrieval suites
    "ccb_mcp_crossrepo_tracing_": "ccb_mcp_crossrepo_tracing",
    "ccb_mcp_security_": "ccb_mcp_security",
    "ccb_mcp_migration_": "ccb_mcp_migration",
    "ccb_mcp_incident_": "ccb_mcp_incident",
    "ccb_mcp_onboarding_": "ccb_mcp_onboarding",
    "ccb_mcp_compliance_": "ccb_mcp_compliance",
    "ccb_mcp_crossorg_": "ccb_mcp_crossorg",
    "ccb_mcp_domain_": "ccb_mcp_domain",
    "ccb_mcp_org_": "ccb_mcp_org",
    "ccb_mcp_platform_": "ccb_mcp_platform",
}

# Legacy hardcoded list — kept for backward compatibility (rerun_failed.py imports it).
# New code should use discover_configs(run_dir) from config_utils instead.
CONFIGS = ["baseline", "sourcegraph_full", "sourcegraph_isolated",
           "baseline-local-direct", "mcp-remote-direct",
           "baseline-local-artifact", "mcp-remote-artifact"]

SELECTION_CONFIG = Path(__file__).resolve().parent.parent / "configs" / "selected_benchmark_tasks.json"

# Benchmarks excluded from gap analysis (no run configs or intentionally skipped)
GAP_EXCLUDED_SUITES = {"ccb_dependeval"}

# Configs intentionally missing for certain suites (e.g., DIBench MCP archived)
GAP_EXCLUDED_SUITE_CONFIGS = {
    ("ccb_dibench", "sourcegraph_full"),
}


def should_skip(dirname: str) -> bool:
    return any(pat in dirname for pat in SKIP_PATTERNS)


def detect_suite(dirname: str) -> str | None:
    for prefix, suite in DIR_PREFIX_TO_SUITE.items():
        if dirname.startswith(prefix):
            return suite
    return None


# ---------------------------------------------------------------------------
# Task scanning
# ---------------------------------------------------------------------------

def _dir_mtime_age_hours(dirpath: Path) -> float:
    """Hours since directory was last modified."""
    try:
        mtime = dirpath.stat().st_mtime
        return (time.time() - mtime) / 3600.0
    except OSError:
        return 0.0


def _dir_mtime_iso(dirpath: Path) -> str:
    """Return mtime as ISO string."""
    try:
        mtime = dirpath.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except OSError:
        return ""


def _extract_task_name(dirname: str) -> str:
    """Strip __hash suffix from directory name to get task name."""
    parts = dirname.rsplit("__", 1)
    return parts[0] if len(parts) == 2 else dirname


def _normalize_sdlc_task_name(raw: str) -> str:
    """Normalize SDLC trial task_name from result.json to canonical task ID.

    Handles:
      'camel-routing-arch-001'                     → 'camel-routing-arch-001'  (unchanged)
      'sdlc_design_camel-routing-arch-001_gIhlvn'  → 'camel-routing-arch-001'
      'sdlc_understand_envoy-filter-chain-qa-001_SbCI8g' → 'envoy-filter-chain-qa-001'

    The SDLC runner names tasks as sdlc_{phase}_{task_id}_{6-char-random}.
    Stripping the prefix and suffix recovers the canonical benchmark task ID.
    """
    import re
    # Strip sdlc_{phase}_ prefix
    m = re.match(r"^sdlc_[a-z]+_(.+)$", raw)
    if m:
        raw = m.group(1)
    # Strip trailing _{6-alphanum} random suffix
    m = re.match(r"^(.+)_[A-Za-z0-9]{6}$", raw)
    if m:
        candidate = m.group(1)
        if "-" in candidate:  # sanity: valid task IDs contain hyphens
            raw = candidate
    return raw


def _read_log_tail(task_dir: Path, n: int = 10) -> list[str]:
    """Read last n lines from claude-code.txt transcript."""
    transcript = task_dir / "agent" / "claude-code.txt"
    if not transcript.is_file():
        return []
    try:
        text = transcript.read_text(errors="replace")
        lines = text.strip().splitlines()
        return lines[-n:]
    except OSError:
        return []


def _extract_reward(data: dict) -> float | None:
    """Extract reward from result.json data."""
    verifier = data.get("verifier_result") or {}
    rewards = verifier.get("rewards") or {}
    reward = rewards.get("reward")
    if reward is None:
        reward = rewards.get("score")
    if reward is not None:
        return float(reward)
    return None


def _extract_tokens(data: dict) -> dict:
    """Extract token counts from result.json."""
    agent_result = data.get("agent_result") or {}
    return {
        "input_tokens": agent_result.get("n_input_tokens"),
        "output_tokens": agent_result.get("n_output_tokens"),
    }


def classify_task(task_dir: Path, timeout_hours: float) -> dict:
    """Classify a single task directory into a status record."""
    result_file = task_dir / "result.json"
    task_name = _extract_task_name(task_dir.name)
    dir_mtime = _dir_mtime_iso(task_dir)
    age_hours = _dir_mtime_age_hours(task_dir)

    record = {
        "task_name": task_name,
        "task_dir": str(task_dir),
        "dir_mtime": dir_mtime,
    }

    if not result_file.is_file():
        # No result yet — running or timed out
        if age_hours > timeout_hours:
            record["status"] = "timeout"
        else:
            record["status"] = "running"
        record["reward"] = None
        record["error_fingerprint"] = None
        record["metrics"] = {}
        record["wall_clock_seconds"] = None
        record["timed_out"] = False
        return record

    # Parse result.json
    try:
        data = json.loads(result_file.read_text())
    except (json.JSONDecodeError, OSError):
        record["status"] = "errored"
        record["reward"] = None
        record["error_fingerprint"] = {
            "fingerprint_id": "result_json_corrupt",
            "label": "Corrupt result.json",
            "severity": "infra",
            "advice": "Re-run the task; result.json is unreadable.",
            "matched_text": "",
        }
        record["metrics"] = {}
        record["wall_clock_seconds"] = None
        record["timed_out"] = False
        return record

    # Check for exception
    exception_info = data.get("exception_info")
    reward = _extract_reward(data)
    tokens = _extract_tokens(data)
    wall_clock = data.get("wall_clock_seconds")

    # Override task_name with canonical form from result.json when available.
    # SDLC trial dirs are named sdlc_{phase}_{task}_{random}__hash which
    # produces a truncated/prefixed name via _extract_task_name. The result.json
    # task_name field has the full name; _normalize_sdlc_task_name strips the
    # sdlc_{phase}_ prefix and _{6-char-random} suffix to recover the canonical ID.
    raw_task_name = data.get("task_name", "")
    if raw_task_name:
        record["task_name"] = _normalize_sdlc_task_name(raw_task_name)

    record["reward"] = reward
    record["metrics"] = {k: v for k, v in tokens.items() if v is not None}
    record["wall_clock_seconds"] = wall_clock

    # Extract timestamps
    record["started_at"] = data.get("started_at", "")
    record["finished_at"] = data.get("finished_at", "")

    # Determine exception type for timeout-vs-error classification
    exception_type = ""
    if isinstance(exception_info, dict):
        exception_type = exception_info.get(
            "exception_type", exception_info.get("type", "")
        )

    if (
        exception_info is not None
        and exception_type == "AgentTimeoutError"
        and reward is not None
    ):
        # Agent timed out but verifier scored partial work — treat as scored result
        record["timed_out"] = True
        record["error_fingerprint"] = fingerprint_error(exception_info)
        if reward > 0:
            record["status"] = "completed_pass"
        else:
            record["status"] = "completed_fail"
    elif exception_info is not None:
        record["status"] = "errored"
        record["error_fingerprint"] = fingerprint_error(exception_info)
        record["timed_out"] = False
    else:
        record["timed_out"] = False
        if reward is not None and reward > 0:
            record["status"] = "completed_pass"
        else:
            record["status"] = "completed_fail"
        record["error_fingerprint"] = None

    return record


def scan_all_tasks(
    timeout_hours: float,
    suite_filter: str | None = None,
    config_filter: str | None = None,
    since_minutes: int | None = None,
    failures_only: bool = False,
    include_gaps: bool = False,
) -> dict:
    """Scan runs/official/ and classify all tasks.

    Returns the full output structure ready for JSON serialization.
    """
    tasks = []
    totals = defaultdict(int)
    by_suite = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    error_summary = defaultdict(lambda: {"count": 0, "label": "", "severity": ""})

    if not RUNS_DIR.exists():
        return _build_output(tasks, totals, by_suite, error_summary, include_gaps=include_gaps)

    now = time.time()
    since_cutoff = None
    if since_minutes is not None:
        since_cutoff = now - (since_minutes * 60)

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        if should_skip(run_dir.name):
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
            if not config_path.is_dir():
                continue

            # Walk the config dir for task directories
            for task_dir in _iter_task_dirs(config_path):
                # Apply --since filter
                if since_cutoff is not None:
                    try:
                        mtime = task_dir.stat().st_mtime
                        if mtime < since_cutoff:
                            continue
                    except OSError:
                        continue

                record = classify_task(task_dir, timeout_hours)
                record["suite"] = suite
                record["config"] = config

                # Apply --failures-only filter
                if failures_only and record["status"] in ("completed_pass",):
                    continue

                tasks.append(record)
                totals[record["status"]] += 1
                if record.get("timed_out"):
                    totals["timed_out"] += 1
                by_suite[suite][config][record["status"]] += 1

                # Accumulate error summary
                fp = record.get("error_fingerprint")
                if fp:
                    fp_id = fp["fingerprint_id"]
                    error_summary[fp_id]["count"] += 1
                    error_summary[fp_id]["label"] = fp["label"]
                    error_summary[fp_id]["severity"] = fp["severity"]

    return _build_output(tasks, totals, by_suite, error_summary, include_gaps=include_gaps)


def _iter_task_dirs(config_path: Path):
    """Yield task directories under a config path.

    Handles both layouts:
    - config_path/batch_timestamp/task_name__hash/
    - config_path/task_name__hash/
    """
    if not config_path.is_dir():
        return

    for entry in sorted(config_path.iterdir()):
        if not entry.is_dir():
            continue

        # Skip archived/broken subdirectories at any level
        if should_skip(entry.name):
            continue

        # Check if this is a batch timestamp dir (starts with "20")
        if entry.name.startswith("20"):
            # Timestamp batch dir — task dirs are inside
            for trial_dir in sorted(entry.iterdir()):
                if trial_dir.is_dir() and not trial_dir.name.startswith("20") and not should_skip(trial_dir.name):
                    yield trial_dir
        elif "__" in entry.name:
            # Old-style direct task dir: task_name__hash
            yield entry
        elif entry.name.startswith("ccb_"):
            # New SDLC-style task config dir: ccb_{suite}_{task}_{config}
            # The task-level result.json lives in the trial subdir inside.
            # (The result.json directly here is a batch summary without rewards.)
            for trial_dir in sorted(entry.iterdir()):
                if trial_dir.is_dir() and not should_skip(trial_dir.name):
                    yield trial_dir


def _match_task_id_to_run_name(task_id: str, run_names: set[str]) -> str | None:
    """Match a full task_id from selection config to a truncated run task_name.

    Run task names are derived from directory names which may be truncated.
    Handles:
    - Bidirectional prefix matching
    - ccb_ prefix stripping (selection uses ccb_repoqa-*, runs use repoqa-*)
    - Gap-fill hyphen vs underscore naming variants
    """
    if task_id in run_names:
        return task_id

    # Generate candidate forms of the task_id
    candidates = [task_id]

    # Strip ccb_{benchmark}- prefix (e.g., ccb_repoqa-foo → repoqa-foo)
    if task_id.startswith("ccb_"):
        stripped = task_id[4:]  # remove "ccb_"
        candidates.append(stripped)

    # Gap-fill naming: hyphens vs double underscores
    # e.g., instance_nodebb-nodebb-76c6e3028 vs instance_nodebb__nodebb-76c6e302
    for c in list(candidates):
        if "-" in c and "__" not in c:
            # Try converting first hyphen after "instance_" to "__"
            if c.startswith("instance_"):
                rest = c[len("instance_"):]
                parts = rest.split("-", 1)
                if len(parts) == 2:
                    candidates.append(f"instance_{parts[0]}__{parts[1]}")

    for rn in run_names:
        for cand in candidates:
            if cand.startswith(rn) or rn.startswith(cand):
                return rn
    return None


def compute_gap_analysis(tasks: list[dict]) -> dict | None:
    """Cross-reference expected tasks from selection config against actual runs.

    Returns a gap_analysis dict with missing tasks per suite/config, or None
    if the selection config is unavailable.
    """
    if not SELECTION_CONFIG.is_file():
        return None

    try:
        selection = json.loads(SELECTION_CONFIG.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    expected_tasks = selection.get("tasks", [])
    if not expected_tasks:
        return None

    # Build lookup of actual run task_names per (suite, config)
    actual_by_key: dict[tuple[str, str], set[str]] = defaultdict(set)
    for t in tasks:
        actual_by_key[(t["suite"], t["config"])].add(t["task_name"])

    # Build expected tasks per suite
    expected_by_suite: dict[str, list[dict]] = defaultdict(list)
    for t in expected_tasks:
        expected_by_suite[t["benchmark"]].append(t)

    gaps_by_suite: dict[str, dict] = {}
    total_expected = 0
    total_present = 0
    total_missing = 0

    for suite in sorted(expected_by_suite.keys()):
        if suite in GAP_EXCLUDED_SUITES:
            continue

        suite_expected = expected_by_suite[suite]
        suite_info: dict = {"expected": len(suite_expected), "configs": {}}

        for config in CONFIGS:
            if (suite, config) in GAP_EXCLUDED_SUITE_CONFIGS:
                continue

            run_names = actual_by_key.get((suite, config), set())
            missing = []
            present_count = 0

            for expected_task in suite_expected:
                task_id = expected_task["task_id"]
                match = _match_task_id_to_run_name(task_id, run_names)
                if match is None:
                    missing.append(task_id)
                else:
                    present_count += 1

            total_expected += len(suite_expected)
            total_present += present_count
            total_missing += len(missing)

            suite_info["configs"][config] = {
                "present": present_count,
                "missing_count": len(missing),
                "missing_task_ids": missing,
            }

        if any(
            cfg_info["missing_count"] > 0
            for cfg_info in suite_info["configs"].values()
        ):
            gaps_by_suite[suite] = suite_info

    return {
        "total_expected_task_runs": total_expected,
        "total_present": total_present,
        "total_missing": total_missing,
        "suites_with_gaps": gaps_by_suite,
    }


def _build_output(tasks, totals, by_suite, error_summary, include_gaps: bool = False) -> dict:
    """Assemble the final output dict."""
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": dict(totals),
        "by_suite": {
            suite: {
                config: dict(statuses)
                for config, statuses in configs.items()
            }
            for suite, configs in sorted(by_suite.items())
        },
        "error_summary": dict(error_summary),
        "tasks": tasks,
    }

    if include_gaps:
        gap = compute_gap_analysis(tasks)
        if gap is not None:
            out["gap_analysis"] = gap

    return out


# ---------------------------------------------------------------------------
# Write per-task status.json
# ---------------------------------------------------------------------------

def write_task_status_files(output: dict):
    """Write a status.json alongside each task's result.json."""
    for task in output["tasks"]:
        task_dir = Path(task["task_dir"])
        if not task_dir.is_dir():
            continue

        status_data = {
            "task_name": task["task_name"],
            "suite": task.get("suite", ""),
            "config": task.get("config", ""),
            "status": task["status"],
            "started_at": task.get("started_at", ""),
            "finished_at": task.get("finished_at", ""),
            "wall_clock_seconds": task.get("wall_clock_seconds"),
            "reward": task.get("reward"),
            "error_summary": task.get("error_fingerprint"),
            "metrics": task.get("metrics", {}),
            "log_tail": _read_log_tail(task_dir),
            "generated_at": output["generated_at"],
        }

        status_path = task_dir / "status.json"
        try:
            status_path.write_text(json.dumps(status_data, indent=2) + "\n")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Table output
# ---------------------------------------------------------------------------

def format_table(output: dict) -> str:
    """Format output as compact ASCII tables."""
    lines = []
    gen = output["generated_at"]
    lines.append(f"Benchmark Status Report  (generated: {gen})")
    lines.append("")

    # Totals
    totals = output["totals"]
    timed_out_count = totals.pop("timed_out", 0)
    total_all = sum(totals.values())
    lines.append(f"TOTALS: {total_all} tasks")
    for status in ("running", "completed_pass", "completed_fail", "errored", "timeout"):
        count = totals.get(status, 0)
        if count:
            lines.append(f"  {status:20s} {count:>5d}")
    if timed_out_count:
        lines.append(f"  {'timed_out (scored)':20s} {timed_out_count:>5d}")
    totals["timed_out"] = timed_out_count  # restore for JSON output
    lines.append("")

    # By suite/config breakdown
    by_suite = output["by_suite"]
    if by_suite:
        # Header
        configs_present = set()
        for configs in by_suite.values():
            configs_present.update(configs.keys())
        configs_sorted = sorted(configs_present)

        header = f"{'Suite':25s}"
        for cfg in configs_sorted:
            short = config_short_name(cfg)
            header += f" | {short:>18s}"
        lines.append(header)
        lines.append("-" * len(header))

        for suite in sorted(by_suite.keys()):
            row = f"{suite:25s}"
            for cfg in configs_sorted:
                statuses = by_suite[suite].get(cfg, {})
                p = statuses.get("completed_pass", 0)
                f_ = statuses.get("completed_fail", 0)
                e = statuses.get("errored", 0)
                r = statuses.get("running", 0)
                t = statuses.get("timeout", 0)
                total = p + f_ + e + r + t
                cell = f"{p}/{total}"
                if e:
                    cell += f" ({e}err)"
                if r:
                    cell += f" ({r}run)"
                row += f" | {cell:>18s}"
            lines.append(row)
        lines.append("")

    # Error summary
    error_summary = output["error_summary"]
    if error_summary:
        lines.append("ERROR SUMMARY:")
        for fp_id, info in sorted(error_summary.items(), key=lambda x: -x[1]["count"]):
            lines.append(f"  {info['count']:>3d}x  [{info['severity']:>8s}]  {fp_id}: {info['label']}")
        lines.append("")

    # Gap analysis
    gap = output.get("gap_analysis")
    if gap and gap["total_missing"] > 0:
        lines.append(f"GAP ANALYSIS: {gap['total_missing']} missing task runs "
                      f"(of {gap['total_expected_task_runs']} expected)")
        for suite, info in sorted(gap["suites_with_gaps"].items()):
            for cfg, cfg_info in sorted(info["configs"].items()):
                n = cfg_info["missing_count"]
                if n > 0:
                    short_cfg = cfg.replace("sourcegraph_", "SG_")
                    lines.append(f"  {suite:25s} {short_cfg:12s} {n:>3d} missing")
        lines.append("")

    # Task details (only non-pass or if few tasks)
    non_pass = [t for t in output["tasks"] if t["status"] != "completed_pass"]
    timed_out_pass = [t for t in output["tasks"]
                      if t["status"] == "completed_pass" and t.get("timed_out")]
    notable = non_pass + timed_out_pass
    if notable:
        lines.append(f"NON-PASSING / TIMED-OUT TASKS ({len(notable)}):")
        for t in notable:
            fp_str = ""
            if t.get("error_fingerprint"):
                fp_str = f" [{t['error_fingerprint']['fingerprint_id']}]"
            reward_str = f" reward={t['reward']:.2f}" if t["reward"] is not None else ""
            timeout_str = " [timed_out]" if t.get("timed_out") else ""
            lines.append(f"  {t['status']:16s}  {t.get('suite',''):20s}  {t.get('config',''):18s}  {t['task_name']}{reward_str}{fp_str}{timeout_str}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description="Scan benchmark runs and report aggregate status."
    )
    parser.add_argument(
        "--format", choices=["json", "table"], default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--failures-only", action="store_true",
        help="Only show errored, failed, and timeout tasks",
    )
    parser.add_argument(
        "--since", type=int, default=None, metavar="N",
        help="Only tasks modified in the last N minutes",
    )
    parser.add_argument(
        "--suite", default=None,
        help="Filter to one benchmark suite (e.g., ccb_pytorch)",
    )
    parser.add_argument(
        "--config", default=None,
        help="Filter to one config (baseline, sourcegraph_full)",
    )
    parser.add_argument(
        "--timeout-hours", type=float, default=4.0,
        help="Hours without result.json before marking as timeout (default: 4)",
    )
    parser.add_argument(
        "--write-status", action="store_true",
        help="Write per-task status.json files alongside result.json",
    )
    parser.add_argument(
        "--gap-analysis", action="store_true",
        help="Include gap analysis: cross-reference expected tasks from selection config against actual runs",
    )
    parser.add_argument(
        "--watch", action="store_true",
        help="Continuous re-scan mode",
    )
    parser.add_argument(
        "--interval", type=int, default=60,
        help="Seconds between scans in --watch mode (default: 60)",
    )
    parser.add_argument(
        "--staging", action="store_true",
        help="Scan runs/staging/ instead of runs/official/",
    )
    return parser.parse_args()


def run_once(args) -> dict:
    """Execute a single scan and output results."""
    output = scan_all_tasks(
        timeout_hours=args.timeout_hours,
        suite_filter=args.suite,
        config_filter=args.config,
        since_minutes=args.since,
        failures_only=args.failures_only,
        include_gaps=args.gap_analysis,
    )

    if args.write_status:
        write_task_status_files(output)

    return output


def main():
    global RUNS_DIR
    args = parse_args()

    if args.staging:
        RUNS_DIR = RUNS_DIR_STAGING

    if args.watch:
        try:
            while True:
                # Clear screen for watch mode
                print("\033[2J\033[H", end="")
                output = run_once(args)
                if args.format == "table":
                    print(format_table(output))
                else:
                    print(json.dumps(output, indent=2))
                print(f"\n(refreshing every {args.interval}s — Ctrl+C to stop)")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        output = run_once(args)
        if args.format == "table":
            print(format_table(output))
        else:
            print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
