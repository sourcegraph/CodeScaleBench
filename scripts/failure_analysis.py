#!/usr/bin/env python3
"""Failure analysis engine for CodeContextBench enterprise metrics.

Classifies every failed task by failure mode with context attribution,
distinguishes infrastructure failures from agent limitations, and
generates case studies of context-resolved failures.

Usage:
    python3 scripts/failure_analysis.py
    python3 scripts/failure_analysis.py --help
    python3 scripts/failure_analysis.py --suite ccb_pytorch --config baseline
    python3 scripts/failure_analysis.py --report
    python3 scripts/failure_analysis.py --output failure_analysis.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ensure scripts/ is on path for sibling imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from aggregate_status import (
    RUNS_DIR,
    CONFIGS,
    should_skip,
    detect_suite,
    _iter_task_dirs,
    _extract_task_name,
)
from status_fingerprints import fingerprint_error

logger = logging.getLogger(__name__)

SELECTION_CONFIG = Path(__file__).resolve().parent.parent / "configs" / "selected_benchmark_tasks.json"


# ---------------------------------------------------------------------------
# Failure taxonomy
# ---------------------------------------------------------------------------

FAILURE_TAXONOMY = {
    "context_insufficient": {
        "id": "context_insufficient",
        "label": "Insufficient Context",
        "description": "Agent lacked necessary codebase context to solve the task. Typically few or no search/read calls before attempting a solution.",
        "heuristic": "Fewer than 5 search/read tool calls in baseline, or agent never read the relevant files.",
    },
    "context_misused": {
        "id": "context_misused",
        "label": "Context Misused",
        "description": "Agent gathered context but edited wrong files or applied changes incorrectly.",
        "heuristic": "Agent made >10 search/read calls but edited files that don't overlap with expected targets.",
    },
    "implementation_error": {
        "id": "implementation_error",
        "label": "Implementation Error",
        "description": "Agent understood the problem and found relevant files but produced incorrect code changes.",
        "heuristic": "Agent searched and edited relevant files (>5 tool calls, >0 edits) but verifier rejected the result.",
    },
    "verification_mismatch": {
        "id": "verification_mismatch",
        "label": "Verification Mismatch",
        "description": "Agent may have produced a valid solution but the verifier rejected it due to format/criteria mismatch.",
        "heuristic": "Verifier parse errors or agent completed many edits but got reward=0 with no exception.",
    },
    "infrastructure_failure": {
        "id": "infrastructure_failure",
        "label": "Infrastructure Failure",
        "description": "Task failed due to infrastructure issues (auth, timeout, API errors, Docker problems) rather than agent capability.",
        "heuristic": "Error fingerprint from status_fingerprints.py matches infra/api/setup severity.",
    },
    "scope_exceeded": {
        "id": "scope_exceeded",
        "label": "Scope Exceeded",
        "description": "Task complexity exceeded agent capabilities — agent ran out of context window or time before completing.",
        "heuristic": "Context window exceeded, timeout, or agent made >100 tool calls without converging.",
    },
}


# ---------------------------------------------------------------------------
# Task metadata
# ---------------------------------------------------------------------------

def load_task_metadata() -> dict[str, dict]:
    """Load task metadata from selected_benchmark_tasks.json."""
    if not SELECTION_CONFIG.is_file():
        logger.warning("Selection config not found: %s", SELECTION_CONFIG)
        return {}
    try:
        data = json.loads(SELECTION_CONFIG.read_text())
    except (OSError, json.JSONDecodeError):
        logger.warning("Failed to parse selection config")
        return {}
    result = {}
    for t in data.get("tasks", []):
        task_id = t.get("task_id", "")
        if task_id:
            result[task_id] = t
    return result


def _match_task_to_metadata(task_name: str, metadata: dict[str, dict]) -> Optional[dict]:
    """Match a run task_name to metadata by prefix matching."""
    if task_name in metadata:
        return metadata[task_name]
    for meta_id, meta in metadata.items():
        if meta_id.startswith(task_name) or task_name.startswith(meta_id):
            return meta
        if meta_id.startswith("ccb_"):
            stripped = meta_id[4:]
            if stripped.startswith(task_name) or task_name.startswith(stripped):
                return meta
    return None


# ---------------------------------------------------------------------------
# Per-task extraction
# ---------------------------------------------------------------------------

def _extract_reward(result_data: dict) -> Optional[float]:
    """Extract reward from result.json data."""
    verifier = result_data.get("verifier_result") or {}
    rewards = verifier.get("rewards") or {}
    for key in ("reward", "score"):
        if key in rewards:
            try:
                return float(rewards[key])
            except (TypeError, ValueError):
                continue
    return None


def _extract_tool_counts_from_transcript(transcript_path: Path) -> dict[str, int]:
    """Parse claude-code.txt JSONL to count tool calls by name."""
    counts: dict[str, int] = {}
    if not transcript_path.is_file():
        return counts
    try:
        text = transcript_path.read_text(errors="replace")
    except OSError:
        return counts
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message") or {}
        content = message.get("content") or []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = block.get("name")
                if name:
                    counts[name] = counts.get(name, 0) + 1
    return counts


def _extract_tool_counts_from_trajectory(trajectory_path: Path) -> dict[str, int]:
    """Parse trajectory.json to count tool calls by name."""
    counts: dict[str, int] = {}
    if not trajectory_path.is_file():
        return counts
    try:
        data = json.loads(trajectory_path.read_text())
    except (OSError, json.JSONDecodeError):
        return counts
    for step in data.get("steps") or []:
        for tc in step.get("tool_calls") or []:
            name = tc.get("function_name")
            if name:
                counts[name] = counts.get(name, 0) + 1
    return counts


_READ_TOOLS = {"Read"}
_SEARCH_TOOLS = {"Grep", "Glob", "WebSearch"}
_EDIT_TOOLS = {"Edit", "Write", "NotebookEdit"}
_INFRA_SEVERITIES = {"infra", "api", "setup", "mcp"}
_VERIFIER_SEVERITY = "verifier"


def _is_mcp_tool(name: str) -> bool:
    return name.startswith("mcp__")


def _classify_failure_mode(
    result_data: dict,
    tool_counts: dict[str, int],
    exception_info: Any,
    error_fp: Optional[dict],
) -> tuple[str, str]:
    """Classify a failed task into a failure mode.

    Returns (failure_mode_id, failure_detail).
    """
    total_tools = sum(tool_counts.values())
    search_read_count = (
        tool_counts.get("Read", 0)
        + tool_counts.get("Grep", 0)
        + tool_counts.get("Glob", 0)
        + sum(c for n, c in tool_counts.items() if _is_mcp_tool(n))
    )
    edit_count = sum(tool_counts.get(t, 0) for t in _EDIT_TOOLS)

    # 1. Infrastructure failure — error fingerprint matches infra category
    if error_fp:
        fp_severity = error_fp.get("severity", "")
        fp_id = error_fp.get("fingerprint_id", "")

        if fp_severity in _INFRA_SEVERITIES:
            return "infrastructure_failure", f"Error: {error_fp.get('label', fp_id)}"

        if fp_severity == _VERIFIER_SEVERITY:
            return "verification_mismatch", f"Verifier error: {error_fp.get('label', fp_id)}"

        # Timeout and context window → scope_exceeded
        if fp_id in ("timeout", "context_window_exceeded"):
            return "scope_exceeded", f"{error_fp.get('label', fp_id)}"

    # 2. Very few tool calls → likely infrastructure failure (agent never started)
    if total_tools < 5 and exception_info is not None:
        return "infrastructure_failure", f"Agent made only {total_tools} tool calls before failing"

    # 3. Scope exceeded — very high tool count without success
    if total_tools > 100:
        return "scope_exceeded", f"Agent made {total_tools} tool calls without converging"

    # 4. Context insufficient — few search/read calls
    if search_read_count < 5 and edit_count == 0:
        return "context_insufficient", (
            f"Agent made {search_read_count} search/read calls and 0 edits"
        )

    # 5. Context misused — many searches but few/no edits
    if search_read_count > 10 and edit_count == 0:
        return "context_misused", (
            f"Agent made {search_read_count} search/read calls but 0 edits — "
            "gathered context without applying changes"
        )

    # 6. Context misused — many searches, some edits, but still failed
    if search_read_count > 10 and edit_count > 0:
        return "context_misused", (
            f"Agent made {search_read_count} search/read calls and {edit_count} edits — "
            "may have edited wrong files"
        )

    # 7. Implementation error — some search, some edits, but failed
    if edit_count > 0:
        return "implementation_error", (
            f"Agent searched ({search_read_count} calls), edited ({edit_count} files) "
            "but changes were incorrect"
        )

    # 8. Context insufficient — default for low-activity failures
    if search_read_count < 10:
        return "context_insufficient", (
            f"Agent made {search_read_count} search/read calls — "
            "insufficient context gathering"
        )

    # Fallback
    return "implementation_error", f"Agent made {total_tools} tool calls, {edit_count} edits"


# ---------------------------------------------------------------------------
# Scanning & dedup
# ---------------------------------------------------------------------------

def scan_failed_tasks(
    suite_filter: Optional[str] = None,
    config_filter: Optional[str] = None,
) -> tuple[list[dict], list[dict]]:
    """Scan runs/official/ and extract records for all tasks.

    Returns (all_tasks, failed_tasks) where each is a list of dicts.
    Uses timestamp-based dedup.
    """
    if not RUNS_DIR.exists():
        logger.warning("runs/official/ not found: %s", RUNS_DIR)
        return [], []

    raw_records: list[tuple[str, dict]] = []

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir() or should_skip(run_dir.name):
            continue
        suite = detect_suite(run_dir.name)
        if suite is None:
            continue
        if suite_filter and suite != suite_filter:
            continue

        for config in CONFIGS:
            if config_filter and config != config_filter:
                continue
            config_path = run_dir / config
            if not config_path.is_dir():
                continue

            for task_dir in _iter_task_dirs(config_path):
                result_path = task_dir / "result.json"
                if not result_path.is_file():
                    continue

                try:
                    result_data = json.loads(result_path.read_text())
                except (OSError, json.JSONDecodeError):
                    continue

                # Skip batch-level result.json
                if "n_total_trials" in result_data and "task_name" not in result_data:
                    continue

                task_name = _extract_task_name(task_dir.name)
                reward = _extract_reward(result_data)
                exception_info = result_data.get("exception_info")
                started_at = result_data.get("started_at", "")

                # Get tool counts
                transcript_path = task_dir / "agent" / "claude-code.txt"
                trajectory_path = task_dir / "agent" / "trajectory.json"
                tool_counts = _extract_tool_counts_from_transcript(transcript_path)
                if not tool_counts:
                    tool_counts = _extract_tool_counts_from_trajectory(trajectory_path)

                total_tools = sum(tool_counts.values())
                mcp_count = sum(c for n, c in tool_counts.items() if _is_mcp_tool(n))

                # Error fingerprint
                error_fp = fingerprint_error(exception_info) if exception_info else None

                record = {
                    "task_name": task_name,
                    "suite": suite,
                    "config": config,
                    "reward": reward,
                    "has_exception": exception_info is not None,
                    "tool_call_count": total_tools,
                    "mcp_call_count": mcp_count,
                    "error_fingerprint": error_fp,
                    "_result_data": result_data,
                    "_tool_counts": tool_counts,
                    "_exception_info": exception_info,
                }

                raw_records.append((started_at, record))

    # Timestamp-based dedup
    best: dict[tuple[str, str, str], tuple[str, dict]] = {}
    for started_at, rec in raw_records:
        key = (rec["suite"], rec["config"], rec["task_name"])
        existing = best.get(key)
        if existing is None or started_at > existing[0]:
            best[key] = (started_at, rec)

    all_tasks = [rec for _, rec in best.values()]
    return all_tasks, [t for t in all_tasks if _is_failed(t)]


def _is_failed(task: dict) -> bool:
    """Return True if task failed (reward==0 or errored)."""
    if task.get("has_exception"):
        return True
    reward = task.get("reward")
    if reward is not None and reward == 0.0:
        return True
    return False


# ---------------------------------------------------------------------------
# Failure classification
# ---------------------------------------------------------------------------

def classify_failures(failed_tasks: list[dict]) -> list[dict]:
    """Classify each failed task by failure mode.

    Returns enriched records with failure_mode and failure_detail fields.
    """
    classified = []
    for t in failed_tasks:
        mode, detail = _classify_failure_mode(
            t["_result_data"],
            t["_tool_counts"],
            t["_exception_info"],
            t.get("error_fingerprint"),
        )
        classified.append({
            "task_name": t["task_name"],
            "suite": t["suite"],
            "config": t["config"],
            "reward": t["reward"],
            "has_exception": t["has_exception"],
            "tool_call_count": t["tool_call_count"],
            "mcp_call_count": t["mcp_call_count"],
            "error_fingerprint": t.get("error_fingerprint"),
            "failure_mode": mode,
            "failure_detail": detail,
        })
    return classified


# ---------------------------------------------------------------------------
# Context attribution
# ---------------------------------------------------------------------------

def compute_context_attribution(
    all_tasks: list[dict],
    classified_failures: list[dict],
) -> list[dict]:
    """Compute context impact for each failed task by cross-config comparison.

    Labels:
    - context_resolved: baseline fail + SG_full pass
    - context_partial_help: both fail but SG_full made more tool calls
    - context_no_impact: both fail similarly
    - context_made_worse: baseline pass + SG_full fail
    """
    # Build lookup by (task_name, config)
    task_by_key: dict[tuple[str, str], dict] = {}
    for t in all_tasks:
        task_by_key[(t["task_name"], t["config"])] = t

    attributed = []
    for t in classified_failures:
        task_name = t["task_name"]
        config = t["config"]

        # Find the same task in other configs
        baseline = task_by_key.get((task_name, "baseline"))
        sg_full = task_by_key.get((task_name, "sourcegraph_full"))
        context_impact = _compute_impact(t, config, baseline, sg_full)

        attributed.append({
            **t,
            "context_impact": context_impact,
        })

    return attributed


def _compute_impact(
    failed_task: dict,
    config: str,
    baseline: Optional[dict],
    sg_full: Optional[dict],
) -> str:
    """Determine context impact label for a single failed task."""
    task_name = failed_task["task_name"]

    if config == "baseline":
        # Check if SG_full passed
        if sg_full and not _is_failed(sg_full):
            return "context_resolved"
        if sg_full and _is_failed(sg_full):
            # Both failed — check if SG_full got further
            sg_tools = sg_full.get("tool_call_count", 0)
            bl_tools = failed_task.get("tool_call_count", 0)
            if sg_tools > bl_tools * 1.5:
                return "context_partial_help"
            return "context_no_impact"
        return "no_comparison"

    elif config == "sourcegraph_full":
        # Check if baseline passed
        if baseline and not _is_failed(baseline):
            return "context_made_worse"
        if baseline and _is_failed(baseline):
            return "context_no_impact"
        return "no_comparison"

    elif config == "sourcegraph_full":
        if baseline and not _is_failed(baseline):
            return "context_made_worse"
        if sg_full and not _is_failed(sg_full):
            return "context_partial_help"
        if baseline and _is_failed(baseline):
            return "context_no_impact"
        return "no_comparison"

    return "no_comparison"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def compute_aggregates(attributed: list[dict]) -> dict:
    """Compute aggregate counts per failure_mode."""
    counts: dict[str, int] = defaultdict(int)
    for t in attributed:
        counts[t["failure_mode"]] += 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


def compute_context_summary(attributed: list[dict]) -> dict:
    """Compute counts per context_impact label."""
    counts: dict[str, int] = defaultdict(int)
    for t in attributed:
        counts[t["context_impact"]] += 1
    return dict(sorted(counts.items(), key=lambda x: -x[1]))


def compute_residual_limitations(attributed: list[dict]) -> list[dict]:
    """Find failure modes that persist even in SG_full config.

    These represent fundamental limitations that context alone can't solve.
    """
    sg_full_failures: dict[str, int] = defaultdict(int)
    for t in attributed:
        if t["config"] == "sourcegraph_full":
            sg_full_failures[t["failure_mode"]] += 1

    residuals = []
    for mode, count in sorted(sg_full_failures.items(), key=lambda x: -x[1]):
        taxonomy = FAILURE_TAXONOMY.get(mode, {})
        residuals.append({
            "failure_mode": mode,
            "label": taxonomy.get("label", mode),
            "count_in_sg_full": count,
            "description": taxonomy.get("description", ""),
        })
    return residuals


# ---------------------------------------------------------------------------
# Case studies
# ---------------------------------------------------------------------------

def extract_case_studies(
    all_tasks: list[dict],
    attributed: list[dict],
    max_studies: int = 5,
) -> list[dict]:
    """Extract case studies of context-resolved failures.

    Picks tasks where baseline failed + SG_full passed, sorted by MCP call
    count descending (highest MCP usage = most illustrative).
    """
    # Find context_resolved tasks (baseline failures where SG_full passed)
    task_by_key: dict[tuple[str, str], dict] = {}
    for t in all_tasks:
        task_by_key[(t["task_name"], t["config"])] = t

    candidates = []
    for t in attributed:
        if t["context_impact"] == "context_resolved" and t["config"] == "baseline":
            sg_full = task_by_key.get((t["task_name"], "sourcegraph_full"))
            if sg_full:
                candidates.append({
                    "task_name": t["task_name"],
                    "suite": t["suite"],
                    "baseline_failure_mode": t["failure_mode"],
                    "baseline_failure_detail": t["failure_detail"],
                    "baseline_tool_calls": t["tool_call_count"],
                    "baseline_mcp_calls": t["mcp_call_count"],
                    "sg_full_tool_calls": sg_full.get("tool_call_count", 0),
                    "sg_full_mcp_calls": sg_full.get("mcp_call_count", 0),
                    "sg_full_reward": sg_full.get("reward"),
                })

    # Sort by SG_full MCP calls descending (most illustrative first)
    candidates.sort(key=lambda x: x["sg_full_mcp_calls"], reverse=True)
    return candidates[:max_studies]


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report_markdown(
    attributed: list[dict],
    aggregates: dict,
    context_summary: dict,
    residuals: list[dict],
    case_studies: list[dict],
    metadata: dict[str, dict],
) -> str:
    """Generate failure_analysis.md with executive summary and case studies."""
    lines = []
    lines.append("# Failure Analysis Report")
    lines.append("")
    lines.append(f"*Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*")
    lines.append("")

    # Executive summary
    total_failed = len(attributed)
    context_resolved = context_summary.get("context_resolved", 0)
    context_no_impact = context_summary.get("context_no_impact", 0)
    context_made_worse = context_summary.get("context_made_worse", 0)
    infra_count = aggregates.get("infrastructure_failure", 0)

    lines.append("## Executive Summary")
    lines.append("")
    lines.append(f"Analyzed **{total_failed} failed task runs** across all configurations.")
    lines.append("")
    lines.append(f"- **{context_resolved}** failures were **resolved by context infrastructure** "
                 "(baseline failed, SG_full passed)")
    lines.append(f"- **{infra_count}** failures were **infrastructure-related** "
                 "(auth, timeout, API errors — not agent limitations)")
    lines.append(f"- **{context_no_impact}** failures showed **no context impact** "
                 "(failed in both baseline and SG_full)")
    if context_made_worse > 0:
        lines.append(f"- **{context_made_worse}** failures were **made worse by context** "
                     "(baseline passed, SG_full failed)")
    lines.append("")

    # Context impact summary
    lines.append("## Context Impact Summary")
    lines.append("")
    lines.append("| Impact | Count | Description |")
    lines.append("|--------|------:|-------------|")
    impact_descriptions = {
        "context_resolved": "Baseline failed, SG_full passed",
        "context_partial_help": "Both failed, SG_full got further",
        "context_no_impact": "Both failed similarly",
        "context_made_worse": "Baseline passed, SG_full failed",
        "no_comparison": "Task only in one config",
    }
    for impact, count in context_summary.items():
        desc = impact_descriptions.get(impact, impact)
        lines.append(f"| {impact} | {count} | {desc} |")
    lines.append("")

    # Per-suite breakdown
    lines.append("## Per-Suite Breakdown")
    lines.append("")
    suite_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for t in attributed:
        suite_counts[t["suite"]][t["failure_mode"]] += 1

    lines.append("| Suite | Total | Infrastructure | Context Insufficient | Context Misused | Implementation | Scope Exceeded | Verification |")
    lines.append("|-------|------:|---------------:|---------------------:|----------------:|---------------:|---------------:|-------------:|")
    for suite in sorted(suite_counts.keys()):
        counts = suite_counts[suite]
        total = sum(counts.values())
        lines.append(
            f"| {suite} | {total} "
            f"| {counts.get('infrastructure_failure', 0)} "
            f"| {counts.get('context_insufficient', 0)} "
            f"| {counts.get('context_misused', 0)} "
            f"| {counts.get('implementation_error', 0)} "
            f"| {counts.get('scope_exceeded', 0)} "
            f"| {counts.get('verification_mismatch', 0)} |"
        )
    lines.append("")

    # Residual limitations
    if residuals:
        lines.append("## Residual Limitations (Persist in SG_full)")
        lines.append("")
        for r in residuals:
            lines.append(f"- **{r['label']}** ({r['count_in_sg_full']} tasks): {r['description']}")
        lines.append("")

    # Case studies
    if case_studies:
        lines.append("## Case Studies: Context-Resolved Failures")
        lines.append("")
        lines.append("These tasks failed in baseline but **passed with context infrastructure** (SG_full).")
        lines.append("")
        for i, cs in enumerate(case_studies, 1):
            meta = _match_task_to_metadata(cs["task_name"], metadata)
            lang = (meta or {}).get("language", "unknown")
            diff = (meta or {}).get("difficulty", "unknown")

            lines.append(f"### Case {i}: {cs['task_name']}")
            lines.append("")
            lines.append(f"- **Suite**: {cs['suite']} | **Language**: {lang} | **Difficulty**: {diff}")
            lines.append(f"- **Baseline failure mode**: {cs['baseline_failure_mode']}")
            lines.append(f"- **Baseline detail**: {cs['baseline_failure_detail']}")
            lines.append(f"- **Baseline tool calls**: {cs['baseline_tool_calls']} "
                         f"(MCP: {cs['baseline_mcp_calls']})")
            lines.append(f"- **SG_full tool calls**: {cs['sg_full_tool_calls']} "
                         f"(MCP: {cs['sg_full_mcp_calls']})")
            lines.append(f"- **SG_full reward**: {cs['sg_full_reward']}")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output assembly
# ---------------------------------------------------------------------------

def _clean_for_json(record: dict) -> dict:
    """Remove internal fields (prefixed with _) from a record."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


def build_output(
    attributed: list[dict],
    aggregates: dict,
    context_summary: dict,
    residuals: list[dict],
) -> dict:
    """Assemble the full failure_analysis.json output."""
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "per_task": [_clean_for_json(t) for t in attributed],
        "aggregate": aggregates,
        "context_summary": context_summary,
        "residual_limitations": residuals,
        "failure_taxonomy": FAILURE_TAXONOMY,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Failure analysis engine: failure mode classification and context attribution."
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
        "--report", action="store_true",
        help="Also generate failure_analysis.md report",
    )
    parser.add_argument(
        "--output", default=None, metavar="FILE",
        help="Write JSON output to FILE (default: stdout)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    # Load metadata
    metadata = load_task_metadata()

    # Scan all tasks (need all for cross-config matching)
    all_tasks, failed_tasks = scan_failed_tasks(
        suite_filter=args.suite,
        config_filter=args.config,
    )

    logger.info("Scanned %d total tasks, %d failed", len(all_tasks), len(failed_tasks))

    # Classify failures
    classified = classify_failures(failed_tasks)

    # Context attribution
    attributed = compute_context_attribution(all_tasks, classified)

    # Aggregates
    aggregates = compute_aggregates(attributed)
    context_summary = compute_context_summary(attributed)
    residuals = compute_residual_limitations(attributed)

    # Build output
    output = build_output(attributed, aggregates, context_summary, residuals)

    # Write JSON
    json_str = json.dumps(output, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json_str + "\n")
        print(f"Wrote {len(attributed)} failure records to {args.output}")
    else:
        print(json_str)

    # Optional report
    if args.report:
        case_studies = extract_case_studies(all_tasks, attributed)
        md = generate_report_markdown(
            attributed, aggregates, context_summary, residuals, case_studies, metadata,
        )
        # Determine report path
        if args.output:
            report_path = Path(args.output).with_suffix(".md")
        else:
            report_path = Path("failure_analysis.md")
        report_path.write_text(md + "\n")
        print(f"Wrote failure analysis report to {report_path}")


if __name__ == "__main__":
    main()
