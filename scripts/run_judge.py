#!/usr/bin/env python3
"""Post-verifier LLM judge runner for CodeScaleBench.

Runs the LLM judge on all tasks in a completed Harbor run, writing
judge_result.json alongside each task's result.json.

Usage:
    python3 scripts/run_judge.py --run runs/official/build_baseline_20260219/
    python3 scripts/run_judge.py --run runs/staging/build_baseline_20260219/ --dry-run
    python3 scripts/run_judge.py --run <run_dir> --ensemble --model gpt-4o
    python3 scripts/run_judge.py --run <run_dir> --suite ccb_fix --task ansible
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import sys
import threading
from pathlib import Path
from typing import Optional

# Ensure scripts/ is on path for sibling imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from csb_metrics.judge import LLMJudge, JudgeInput, JudgeResult
from csb_metrics.judge.oracle import discover_oracle
from csb_metrics.discovery import (
    resolve_task_transcript_path,
    _is_batch_dir,
    _is_task_dir,
)
from csb_metrics.extractors import (
    extract_tool_usage_from_transcript,
    extract_tool_usage_from_trajectory,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"

# Patterns indicating directories to skip (from ir_analysis.py)
SKIP_PATTERNS = [
    "__broken_verifier",
    "validation_test",
    "archive",
    "__archived",
    "preamble_test_",
    "__v1_hinted",
]

# Map run directory name prefix -> benchmark suite name
DIR_PREFIX_TO_SUITE: dict[str, str] = {
    # SDLC phase suites (new naming: csb_sdlc_{phase})
    "csb_sdlc_feature_": "csb_sdlc_feature",
    "csb_sdlc_refactor_": "csb_sdlc_refactor",
    "csb_sdlc_debug_": "csb_sdlc_debug",
    "csb_sdlc_design_": "csb_sdlc_design",
    "csb_sdlc_document_": "csb_sdlc_document",
    "csb_sdlc_fix_": "csb_sdlc_fix",
    "csb_sdlc_secure_": "csb_sdlc_secure",
    "csb_sdlc_test_": "csb_sdlc_test",
    "csb_sdlc_understand_": "csb_sdlc_understand",
    # Legacy SDLC phase suites
    "feature_": "ccb_feature",
    "refactor_": "ccb_refactor",
    "build_": "ccb_build",  # legacy run dirs
    "debug_": "ccb_debug",
    "design_": "ccb_design",
    "document_": "ccb_document",
    "fix_": "ccb_fix",
    "secure_": "ccb_secure",
    "test_": "ccb_test",
    "understand_": "ccb_understand",
    # Legacy / specialised benchmarks
    "bigcode_mcp_": "ccb_largerepo",
    "bigcode_sgcompare_": "ccb_largerepo",
    "bigcode_": "ccb_largerepo",
    "codereview_": "ccb_codereview",
    "crossrepo_": "ccb_crossrepo",
    "dibench_": "ccb_dibench",
    "enterprise_": "ccb_enterprise",
    "governance_": "ccb_governance",
    "investigation_": "ccb_investigation",
    "k8s_docs_": "ccb_k8sdocs",
    "k8s_": "ccb_k8sdocs",
    "linuxflbench_": "ccb_linuxflbench",
    "locobench_": "ccb_locobench",
    "pytorch_": "ccb_pytorch",
    "repoqa_": "ccb_repoqa",
    "security_": "ccb_security",
    "swebenchpro_gapfill_": "ccb_swebenchpro",
    "swebenchpro_": "ccb_swebenchpro",
    "sweperf_": "ccb_sweperf",
    "tac_": "ccb_tac",
    "paired_rerun_dibench_": "ccb_dibench",
    "paired_rerun_crossrepo_": "ccb_crossrepo",
    "paired_rerun_pytorch_": "ccb_pytorch",
    # MCP-unique suites (new naming: csb_org_{suite})
    "csb_org_crossrepo_tracing_": "csb_org_crossrepo_tracing",
    "csb_org_security_": "csb_org_security",
    "csb_org_migration_": "csb_org_migration",
    "csb_org_incident_": "csb_org_incident",
    "csb_org_onboarding_": "csb_org_onboarding",
    "csb_org_compliance_": "csb_org_compliance",
    "csb_org_crossorg_": "csb_org_crossorg",
    "csb_org_domain_": "csb_org_domain",
    "csb_org_org_": "csb_org_org",
    "csb_org_platform_": "csb_org_platform",
    "csb_org_crossrepo_": "csb_org_crossrepo",
    # Legacy MCP-unique prefixes (backward compat)
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

DEFAULT_MODEL = "gpt-4o"
DEFAULT_VERIFIER_WEIGHT = 0.6


# ---------------------------------------------------------------------------
# Hybrid evaluation helpers
# ---------------------------------------------------------------------------


def _find_criteria_json(task_id: str, benchmark: str, benchmarks_dir: Path) -> Optional[Path]:
    """Locate tests/criteria.json for a task in the benchmarks directory.

    Searches benchmarks/<benchmark>/<task_id>/tests/criteria.json.
    Also tries slug variants (lower-case, underscore → hyphen normalization).

    Returns the Path if found, else None.
    """
    # Direct lookup: benchmark/task_id/tests/criteria.json
    suite_dir = benchmarks_dir / benchmark
    if suite_dir.is_dir():
        candidate = suite_dir / task_id / "tests" / "criteria.json"
        if candidate.is_file():
            return candidate
        # Normalize: task_id may differ in case or use underscores vs hyphens
        slug = task_id.lower().replace("_", "-")
        for subdir in suite_dir.iterdir():
            if subdir.is_dir() and subdir.name.lower().replace("_", "-") == slug:
                candidate = subdir / "tests" / "criteria.json"
                if candidate.is_file():
                    return candidate
    return None


def _load_criteria_json(path: Path) -> list[dict]:
    """Load and return criteria list from criteria.json.

    Returns empty list on error.
    """
    try:
        data = json.loads(path.read_text())
        if isinstance(data, list):
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return []


# ---------------------------------------------------------------------------
# Run directory scanning
# ---------------------------------------------------------------------------


def _should_skip(dirname: str) -> bool:
    """Return True if the directory should be skipped."""
    return any(pat in dirname for pat in SKIP_PATTERNS)


def _infer_benchmark(run_dir_name: str) -> str:
    """Infer benchmark suite name from run directory name."""
    name = run_dir_name.lower()
    for prefix, suite in DIR_PREFIX_TO_SUITE.items():
        if name.startswith(prefix):
            return suite
    # Fallback: extract first word before _baseline or _sourcegraph
    m = re.match(r"^([a-z_]+?)_(?:baseline|sourcegraph|opus|sonnet|haiku)", name)
    if m:
        candidate = m.group(1)
        if candidate.startswith(("ccb_", "csb_")):
            return candidate
        return f"csb_sdlc_{candidate}"
    return "unknown"


def _discover_tasks(
    run_dir: Path,
    suite_filter: Optional[str],
    task_filter: Optional[str],
) -> list[dict]:
    """Discover all eligible task directories under a run dir.

    Returns a list of dicts with keys:
        task_dir, result_path, task_id, benchmark, config
    """
    tasks: list[dict] = []
    run_name = run_dir.name

    if not run_dir.is_dir():
        return tasks

    for config_dir in sorted(run_dir.iterdir()):
        if not config_dir.is_dir():
            continue
        if _should_skip(config_dir.name):
            continue

        config_name = config_dir.name
        benchmark = _infer_benchmark(run_name)

        # Apply suite filter
        if suite_filter and suite_filter not in benchmark:
            continue

        for batch_dir in sorted(config_dir.iterdir()):
            if not batch_dir.is_dir():
                continue
            if not _is_batch_dir(batch_dir):
                continue
            if _should_skip(batch_dir.name):
                continue

            for task_dir in sorted(batch_dir.iterdir()):
                if not _is_task_dir(task_dir):
                    continue
                if _should_skip(task_dir.name):
                    continue

                result_path = task_dir / "result.json"
                if not result_path.is_file():
                    continue

                # Extract task_id from result.json
                try:
                    data = json.loads(result_path.read_text())
                    task_id = data.get("task_name") or ""
                    if not task_id:
                        task_id = task_dir.name.split("__")[0]
                except (OSError, json.JSONDecodeError):
                    task_id = task_dir.name.split("__")[0]

                # Apply task filter
                if task_filter and task_filter not in task_id:
                    continue

                tasks.append(
                    {
                        "task_dir": task_dir,
                        "result_path": result_path,
                        "task_id": task_id,
                        "benchmark": benchmark,
                        "config": config_name,
                    }
                )

    return tasks


# ---------------------------------------------------------------------------
# Data extraction helpers
# ---------------------------------------------------------------------------


def _load_verifier_reward(result_path: Path) -> Optional[float]:
    """Extract verifier reward from result.json."""
    try:
        data = json.loads(result_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None

    verifier_result = data.get("verifier_result") or {}
    rewards = verifier_result.get("rewards") or {}
    for key in ("reward", "score"):
        if key in rewards:
            try:
                return float(rewards[key])
            except (TypeError, ValueError):
                continue
    return None


def _load_task_description(task_dir: Path) -> str:
    """Read task instruction text from agent/instruction.txt.

    Strips the MCP preamble if present (SG_full runs prepend
    "# Searching Sourcegraph ..." before the actual task instruction,
    separated by a "---" line). The judge should only see the task.
    """
    instruction_path = task_dir / "agent" / "instruction.txt"
    if instruction_path.is_file():
        try:
            text = instruction_path.read_text(errors="replace")
            # Strip MCP preamble: everything before the first "---" separator
            if text.lstrip().startswith("# Searching Sourcegraph"):
                parts = re.split(r"\n---\n", text, maxsplit=1)
                if len(parts) == 2:
                    text = parts[1].lstrip()
            # Truncate to avoid overwhelming the judge prompt
            return text[:3000] if len(text) > 3000 else text
        except OSError:
            pass
    return "(no instruction available)"


# Budget for agent output in the judge prompt.  GPT-4o has 128K context;
# the rest of the prompt (task description, oracle, template) is ≈5-8K chars.
# 50K chars ≈ 12K tokens — leaves plenty of headroom.
_AGENT_OUTPUT_BUDGET = 50_000


def _extract_agent_output(task_dir: Path) -> str:
    """Extract the agent's code output from the transcript.

    Collects ALL Edit/Write tool calls without per-item truncation.
    Only a single total-length budget is applied at the end so the
    judge sees as much of the actual work as possible.
    """
    transcript_path = resolve_task_transcript_path(task_dir)
    if not transcript_path.is_file():
        return "(no transcript available)"

    try:
        lines = transcript_path.read_text(errors="replace").splitlines()
    except OSError:
        return "(transcript read error)"

    edits: list[str] = []
    writes: dict[str, str] = {}  # path -> content (last-write-wins)

    for line in lines:
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
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name") or ""
            inp = block.get("input") or {}

            if name == "Edit":
                fp = inp.get("file_path", "")
                old_str = inp.get("old_string", "")
                new_str = inp.get("new_string", "")
                if fp and (new_str or old_str):
                    edits.append(f"Edit {fp}:\n-{old_str}\n+{new_str}")

            elif name == "Write":
                fp = inp.get("file_path", "")
                content_str = inp.get("content", "")
                if fp and content_str:
                    # Keep last write to each path (agent may overwrite)
                    writes[fp] = content_str

    parts: list[str] = []
    if edits:
        parts.append("=== Code Edits ===\n" + "\n---\n".join(edits))
    if writes:
        write_items = [f"Write {fp}:\n{body}" for fp, body in writes.items()]
        parts.append("=== Written Files ===\n" + "\n---\n".join(write_items))

    if not parts:
        return "(no code changes recorded)"

    summary = "\n\n".join(parts)

    if len(summary) > _AGENT_OUTPUT_BUDGET:
        summary = summary[:_AGENT_OUTPUT_BUDGET] + (
            f"\n\n[... truncated — full output is {len(summary)} chars, "
            f"budget is {_AGENT_OUTPUT_BUDGET} ...]"
        )

    return summary


def _extract_tool_calls_summary(task_dir: Path) -> str:
    """Summarise tool call usage from trajectory or transcript."""
    trajectory_path = task_dir / "agent" / "trajectory.json"
    tool_usage = extract_tool_usage_from_trajectory(trajectory_path)
    if tool_usage.get("tool_calls_total") is None:
        transcript_path = resolve_task_transcript_path(task_dir)
        tool_usage = extract_tool_usage_from_transcript(transcript_path)

    by_name = tool_usage.get("tool_calls_by_name") or {}
    if not by_name:
        return "(no tool calls recorded)"

    # Sort by count descending
    sorted_tools = sorted(by_name.items(), key=lambda x: x[1], reverse=True)
    parts = [f"{name}:{count}" for name, count in sorted_tools[:15]]
    total = tool_usage.get("tool_calls_total", 0)
    mcp = tool_usage.get("tool_calls_mcp", 0)
    return f"total={total} mcp={mcp} | " + " ".join(parts)


def _extract_mcp_tools_used(task_dir: Path) -> list[str]:
    """Return list of distinct MCP tool names used."""
    trajectory_path = task_dir / "agent" / "trajectory.json"
    tool_usage = extract_tool_usage_from_trajectory(trajectory_path)
    if tool_usage.get("tool_calls_total") is None:
        transcript_path = resolve_task_transcript_path(task_dir)
        tool_usage = extract_tool_usage_from_transcript(transcript_path)

    by_name = tool_usage.get("tool_calls_by_name") or {}
    return [name for name in by_name if name.startswith("mcp__")]


# ---------------------------------------------------------------------------
# Core judge runner
# ---------------------------------------------------------------------------


def _run_single_task(
    task_info: dict,
    judge: LLMJudge,
    benchmarks_dir: Path,
    force: bool,
    dry_run: bool,
    counter: dict,
    counter_lock: threading.Lock,
    total: int,
    use_ensemble: bool = False,
    ensemble_rounds: int = 3,
    hybrid: bool = False,
    verifier_weight: float = DEFAULT_VERIFIER_WEIGHT,
) -> tuple[str, bool, Optional[str]]:
    """Evaluate a single task.  Returns (task_id, success, error_msg)."""
    task_dir: Path = task_info["task_dir"]
    result_path: Path = task_info["result_path"]
    task_id: str = task_info["task_id"]
    benchmark: str = task_info["benchmark"]
    config: str = task_info["config"]

    # Increment and capture index
    with counter_lock:
        counter["n"] += 1
        idx = counter["n"]

    judge_result_path = task_dir / "judge_result.json"

    # Skip if already judged (unless --force)
    if judge_result_path.is_file() and not force:
        # Discover oracle to get confidence for --dry-run style output
        oracle = discover_oracle(task_id, benchmark, benchmarks_dir)
        print(f"[{idx}/{total}] {task_id} SKIP (already judged, confidence={oracle.confidence})")
        return task_id, True, None

    # Dry-run mode: just report oracle confidence
    if dry_run:
        oracle = discover_oracle(task_id, benchmark, benchmarks_dir)
        print(f"[{idx}/{total}] {task_id} benchmark={benchmark} config={config} oracle_confidence={oracle.confidence}")
        return task_id, True, None

    # Load verifier reward
    verifier_reward = _load_verifier_reward(result_path)
    if verifier_reward is None:
        verifier_reward = 0.0

    # Discover oracle
    oracle = discover_oracle(task_id, benchmark, benchmarks_dir)

    # Load task data
    task_description = _load_task_description(task_dir)
    agent_output = _extract_agent_output(task_dir)
    tool_calls_summary = _extract_tool_calls_summary(task_dir)
    mcp_tools = _extract_mcp_tools_used(task_dir)

    # Build JudgeInput
    judge_input = JudgeInput(
        task_id=task_id,
        task_description=task_description,
        code_changes=agent_output,
        tool_calls=tool_calls_summary,
        verifier_reward=verifier_reward,
        oracle_ground_truth=oracle.ground_truth_text,
        oracle_expected_approach=oracle.expected_approach,
        oracle_evaluation_criteria=oracle.evaluation_criteria,
        oracle_context_files=oracle.context_files,
        mcp_tools_used=mcp_tools,
    )

    # Call judge
    try:
        if use_ensemble:
            result: JudgeResult = judge.evaluate_with_voting(judge_input, rounds=ensemble_rounds)
        else:
            result = judge.evaluate(judge_input)
    except Exception as exc:
        err = f"judge error: {exc}"
        print(f"[{idx}/{total}] {task_id} FAIL {err}")
        return task_id, False, err

    # Patch benchmark and config into result
    result.benchmark = benchmark
    result.config = config

    # --- Hybrid evaluation: rubric scoring from criteria.json ---
    if hybrid:
        criteria_path = _find_criteria_json(task_id, benchmark, benchmarks_dir)
        if criteria_path is not None:
            criteria = _load_criteria_json(criteria_path)
            if criteria:
                try:
                    crit_scores, rubric_score = judge.evaluate_with_criteria(
                        judge_input, criteria
                    )
                    result.criteria_scores = crit_scores
                    result.rubric_score = rubric_score
                    composite = (
                        verifier_weight * verifier_reward
                        + (1.0 - verifier_weight) * rubric_score
                    )
                    result.hybrid_composite = round(composite, 4)
                    result.verifier_weight = verifier_weight
                except Exception as exc:
                    # Non-fatal: log and continue without rubric scores
                    print(
                        f"[{idx}/{total}] {task_id} WARN rubric scoring failed: {exc}"
                    )

    # Write judge_result.json
    try:
        judge_result_path.write_text(
            json.dumps(result.to_dict(), indent=2), encoding="utf-8"
        )
    except OSError as exc:
        err = f"write error: {exc}"
        print(f"[{idx}/{total}] {task_id} FAIL {err}")
        return task_id, False, err

    # Progress output
    dims = result.dimension_scores
    correctness = dims.get("correctness", 0.0)
    completeness = dims.get("completeness", 0.0)
    oracle_conf = oracle.confidence
    extra = ""
    if result.hybrid_composite is not None:
        extra = f" rubric={result.rubric_score:.2f} hybrid={result.hybrid_composite:.2f}"
    print(
        f"[{idx}/{total}] {task_id} "
        f"correctness={correctness:.2f} completeness={completeness:.2f} "
        f"judge_score={result.judge_score:.2f} (confidence={oracle_conf}){extra}"
    )

    return task_id, True, None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Run LLM judge on all tasks in a completed Harbor run.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--run", required=True, metavar="DIR", help="Run directory to evaluate")
    p.add_argument("--suite", metavar="FILTER", help="Only evaluate tasks whose benchmark matches this substring")
    p.add_argument("--task", metavar="FILTER", help="Only evaluate tasks whose task_id contains this substring")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Judge model (OpenAI: gpt-4o, gpt-4o-mini; Anthropic: claude-*)")
    p.add_argument("--rounds", type=int, default=1, help="Number of scoring rounds (overridden by --ensemble)")
    p.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature")
    p.add_argument("--ensemble", action="store_true", help="Enable 3-round majority-vote ensemble scoring")
    p.add_argument("--dry-run", action="store_true", help="Print task list with oracle confidence; skip API calls")
    p.add_argument("--force", action="store_true", help="Re-evaluate tasks that already have judge_result.json")
    p.add_argument(
        "--hybrid",
        action="store_true",
        help=(
            "Enable hybrid evaluation: auto-detect tests/criteria.json and include "
            "rubric scoring. Computes composite = verifier_weight * verifier_reward + "
            "(1 - verifier_weight) * rubric_score."
        ),
    )
    p.add_argument(
        "--hybrid-weight",
        type=float,
        default=DEFAULT_VERIFIER_WEIGHT,
        metavar="W",
        help=(
            f"Verifier reward weight for hybrid composite (default: {DEFAULT_VERIFIER_WEIGHT}). "
            "Must be in [0, 1]. Rubric weight = 1 - W."
        ),
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    run_dir = Path(args.run)
    if not run_dir.is_dir():
        print(f"ERROR: --run directory does not exist: {run_dir}", file=sys.stderr)
        return 1

    # Discover tasks
    tasks = _discover_tasks(run_dir, args.suite, args.task)
    if not tasks:
        print(f"No tasks found under {run_dir}")
        return 0

    total = len(tasks)
    print(f"Found {total} task(s) to evaluate in {run_dir.name}")

    if args.dry_run:
        counter: dict = {"n": 0}
        lock = threading.Lock()
        for t in tasks:
            oracle = discover_oracle(t["task_id"], t["benchmark"], BENCHMARKS_DIR)
            with lock:
                counter["n"] += 1
                idx = counter["n"]
            print(
                f"[{idx}/{total}] {t['task_id']} "
                f"benchmark={t['benchmark']} config={t['config']} "
                f"oracle_confidence={oracle.confidence}"
            )
        return 0

    # Validate hybrid weight
    verifier_weight = args.hybrid_weight
    if not (0.0 <= verifier_weight <= 1.0):
        print(
            f"ERROR: --hybrid-weight must be in [0, 1], got {verifier_weight}",
            file=sys.stderr,
        )
        return 1

    if args.hybrid:
        print(
            f"Hybrid mode enabled: verifier_weight={verifier_weight:.2f}, "
            f"rubric_weight={1.0 - verifier_weight:.2f}"
        )

    # Build judge
    effective_rounds = 3 if args.ensemble else args.rounds
    judge = LLMJudge(
        model=args.model,
        temperature=args.temperature,
        rounds=effective_rounds,
    )

    # Shared counter
    counter = {"n": 0}
    counter_lock = threading.Lock()

    # Run with thread pool
    failures: list[str] = []

    def _worker(task_info: dict) -> tuple[str, bool, Optional[str]]:
        return _run_single_task(
            task_info, judge, BENCHMARKS_DIR, args.force, False,
            counter, counter_lock, total,
            use_ensemble=args.ensemble,
            ensemble_rounds=effective_rounds,
            hybrid=args.hybrid,
            verifier_weight=verifier_weight,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_worker, t): t for t in tasks}
        for future in concurrent.futures.as_completed(futures):
            task_id, success, error_msg = future.result()
            if not success:
                failures.append(task_id)

    if failures:
        print(f"\nFAILED ({len(failures)}/{total}):", file=sys.stderr)
        for tid in failures:
            print(f"  {tid}", file=sys.stderr)
        return 1

    print(f"\nAll {total} task(s) judged successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
