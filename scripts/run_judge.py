#!/usr/bin/env python3
"""Post-verifier LLM judge runner for CodeContextBench.

Runs the LLM judge on all tasks in a completed Harbor run, writing
judge_result.json alongside each task's result.json.

Usage:
    python3 scripts/run_judge.py --run runs/official/build_baseline_20260219/
    python3 scripts/run_judge.py --run runs/staging/build_baseline_20260219/ --dry-run
    python3 scripts/run_judge.py --run <run_dir> --ensemble --model claude-haiku-4-5-20251001
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

from ccb_metrics.judge import LLMJudge, JudgeInput, JudgeResult, OracleBundle
from ccb_metrics.judge.oracle import discover_oracle
from ccb_metrics.discovery import (
    resolve_task_transcript_path,
    _is_batch_dir,
    _is_task_dir,
)
from ccb_metrics.extractors import (
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
    # SDLC phase suites
    "build_": "ccb_build",
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
}

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


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
        return f"ccb_{candidate}" if not candidate.startswith("ccb_") else candidate
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
    """Read task instruction text from agent/instruction.txt."""
    instruction_path = task_dir / "agent" / "instruction.txt"
    if instruction_path.is_file():
        try:
            text = instruction_path.read_text(errors="replace")
            # Truncate to avoid overwhelming the judge prompt
            return text[:3000] if len(text) > 3000 else text
        except OSError:
            pass
    return "(no instruction available)"


def _extract_agent_output(task_dir: Path) -> str:
    """Extract a summary of the agent's code output from the transcript.

    Collects Edit/Write tool calls and formats as a readable summary.
    """
    transcript_path = resolve_task_transcript_path(task_dir)
    if not transcript_path.is_file():
        return "(no transcript available)"

    try:
        lines = transcript_path.read_text(errors="replace").splitlines()
    except OSError:
        return "(transcript read error)"

    edits: list[str] = []
    writes: list[str] = []

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
                new_str = inp.get("new_string", "")
                if fp and new_str and len(edits) < 5:
                    snippet = new_str[:200] if len(new_str) > 200 else new_str
                    edits.append(f"Edit {fp}:\n{snippet}")

            elif name == "Write":
                fp = inp.get("file_path", "")
                content_str = inp.get("content", "")
                if fp and content_str and len(writes) < 3:
                    snippet = content_str[:200] if len(content_str) > 200 else content_str
                    writes.append(f"Write {fp}:\n{snippet}")

    parts: list[str] = []
    if edits:
        parts.append("=== Code Edits ===\n" + "\n---\n".join(edits))
    if writes:
        parts.append("=== New Files ===\n" + "\n---\n".join(writes))

    if not parts:
        return "(no code changes recorded)"

    summary = "\n\n".join(parts)
    # Keep total length manageable
    return summary[:4000] if len(summary) > 4000 else summary


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
    print(
        f"[{idx}/{total}] {task_id} "
        f"correctness={correctness:.2f} completeness={completeness:.2f} "
        f"judge_score={result.judge_score:.2f} (confidence={oracle_conf})"
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
    p.add_argument("--model", default=DEFAULT_MODEL, help="Anthropic model identifier for judge")
    p.add_argument("--rounds", type=int, default=1, help="Number of scoring rounds (overridden by --ensemble)")
    p.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature")
    p.add_argument("--ensemble", action="store_true", help="Enable 3-round majority-vote ensemble scoring")
    p.add_argument("--dry-run", action="store_true", help="Print task list with oracle confidence; skip API calls")
    p.add_argument("--force", action="store_true", help="Re-evaluate tasks that already have judge_result.json")
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
