#!/usr/bin/env python3
"""Batch re-extract task_metrics.json for all active task directories.

Walks runs/official/ and re-runs extract_task_metrics on every task directory
that contains a result.json. This fixes inflated token counts from the old
extraction logic that used cumulative n_input_tokens instead of transcript-sourced
cache-aware token breakdown.

Usage:
    python3 scripts/reextract_all_metrics.py [--dry-run] [--filter SUITE]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure scripts/ is on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from extract_task_metrics import process_task_dir
from ccb_metrics.task_selection import load_selected_tasks, build_task_index, enrich_task_metrics

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs" / "official"

SKIP_PATTERNS = ["__broken_verifier", "validation_test", "archive", "__archived"]

DIR_PREFIX_TO_SUITE = {
    "bigcode_mcp_": "ccb_largerepo",
    "bigcode_sgcompare_": "ccb_largerepo",
    "codereview_": "ccb_codereview",
    "crossrepo_": "ccb_crossrepo",
    "dibench_": "ccb_dibench",
    "investigation_": "ccb_investigation",
    "k8s_docs_": "ccb_k8sdocs",
    "linuxflbench_": "ccb_linuxflbench",
    "locobench_": "ccb_locobench",
    "pytorch_": "ccb_pytorch",
    "repoqa_": "ccb_repoqa",
    "swebenchpro_": "ccb_swebenchpro",
    "sweperf_": "ccb_sweperf",
    "tac_": "ccb_tac",
    "paired_rerun_dibench_": "ccb_dibench",
    "paired_rerun_crossrepo_": "ccb_crossrepo",
    "paired_rerun_pytorch_": "ccb_pytorch",
    "paired_rerun_": None,  # multi-benchmark — infer per task
}

CONFIGS = ["baseline", "sourcegraph_base", "sourcegraph_full", "sourcegraph", "deepsearch"]


def should_skip(dirname: str) -> bool:
    return any(pat in dirname for pat in SKIP_PATTERNS)


def suite_from_task_id(task_id: str) -> str | None:
    """Infer benchmark suite from task ID patterns."""
    if task_id.startswith("instance_"):
        return "ccb_swebenchpro"
    if task_id.startswith("sgt-"):
        return "ccb_pytorch"
    if task_id.startswith("big-code-"):
        return "ccb_largerepo"
    if task_id.startswith("dibench-"):
        return "ccb_dibench"
    if task_id.startswith("cr-"):
        return "ccb_codereview"
    if task_id.endswith("-doc-001"):
        return "ccb_k8sdocs"
    if task_id.startswith("lfl-"):
        return "ccb_linuxflbench"
    if task_id.startswith("bug_localization_") or task_id.startswith("refactor_rename_") or task_id.startswith("cross_file_reasoning_"):
        return "ccb_crossrepo"
    if "_expert_" in task_id:
        return "ccb_locobench"
    if task_id.startswith("multifile_editing-") or task_id.startswith("file_span_fix-") or task_id.startswith("dependency_recognition-"):
        return "ccb_dependeval"
    if task_id.startswith("repoqa-"):
        return "ccb_repoqa"
    if task_id.startswith("sweperf-"):
        return "ccb_sweperf"
    if task_id.startswith("tac-") or task_id.startswith("simple_test_"):
        return "ccb_tac"
    if task_id.startswith("api_upgrade_") or task_id.startswith("hyperloglog") or task_id.startswith("write-unit-test"):
        return "ccb_tac"
    if task_id.startswith("sweperf_") or task_id.startswith("django_perf_"):
        return "ccb_sweperf"
    if "answer_extraction" in task_id or "function_recall" in task_id or "question_answer" in task_id:
        return "ccb_repoqa"
    return None


def suite_from_run_dir(name: str) -> str | None:
    for prefix, suite in DIR_PREFIX_TO_SUITE.items():
        if name.startswith(prefix):
            # None means multi-benchmark — will be resolved per-task
            return suite if suite is not None else "__multi__"
    # Gap-fill
    if name.startswith("swebenchpro_gapfill_"):
        return "ccb_swebenchpro"
    return None


def _is_batch_timestamp(name: str) -> bool:
    """Check if directory name is a batch timestamp like 2026-02-05__22-53-44."""
    import re
    return bool(re.match(r"\d{4}-\d{2}-\d{2}__\d{2}-\d{2}-\d{2}", name))


def _is_task_dir(d: Path) -> bool:
    """A task dir has result.json AND agent/ subdirectory (or at minimum result.json with task data)."""
    result_json = d / "result.json"
    if not result_json.is_file():
        return False
    # Batch-level result.json has n_total_trials, task-level has task_name or agent_result
    try:
        data = json.loads(result_json.read_text())
        if "n_total_trials" in data and "task_name" not in data:
            return False  # batch-level
    except (json.JSONDecodeError, OSError):
        return False
    return True


def find_task_dirs(runs_dir: Path, suite_filter: str | None = None) -> list[tuple[Path, str, str]]:
    """Find all (task_dir, benchmark, config) tuples in runs/official/.

    Handles two layouts:
      config/batch_ts/task__hash/result.json
      config/task__hash/result.json  (some older runs)
    """
    results = []

    for run_dir in sorted(runs_dir.iterdir()):
        if not run_dir.is_dir():
            continue
        if should_skip(run_dir.name):
            continue

        suite = suite_from_run_dir(run_dir.name)
        if suite is None:
            continue
        if suite_filter and suite != suite_filter:
            continue

        for config_name in CONFIGS:
            config_dir = run_dir / config_name
            if not config_dir.is_dir():
                continue

            for subdir in sorted(config_dir.iterdir()):
                if not subdir.is_dir():
                    continue
                if should_skip(subdir.name):
                    continue

                if _is_batch_timestamp(subdir.name):
                    # This is a batch dir — look for task dirs inside
                    for task_dir in sorted(subdir.iterdir()):
                        if not task_dir.is_dir():
                            continue
                        if should_skip(task_dir.name):
                            continue
                        if _is_task_dir(task_dir):
                            # Resolve multi-benchmark suite from task_id
                            task_suite = suite
                            if suite == "__multi__":
                                task_name = task_dir.name.rsplit("__", 1)[0]
                                task_suite = suite_from_task_id(task_name) or "unknown"
                            if suite_filter and task_suite != suite_filter:
                                continue
                            results.append((task_dir, task_suite, config_name))
                elif _is_task_dir(subdir):
                    # Task dir directly under config
                    task_suite = suite
                    if suite == "__multi__":
                        task_name = subdir.name.rsplit("__", 1)[0]
                        task_suite = suite_from_task_id(task_name) or "unknown"
                    if suite_filter and task_suite != suite_filter:
                        continue
                    results.append((subdir, task_suite, config_name))

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch re-extract task_metrics.json")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be re-extracted without writing")
    parser.add_argument("--filter", type=str, default=None, help="Only re-extract for this suite (e.g. ccb_pytorch)")
    parser.add_argument("--selected-tasks", type=Path,
                       default=Path(__file__).resolve().parent.parent / "configs" / "selected_benchmark_tasks.json")
    args = parser.parse_args()

    task_dirs = find_task_dirs(RUNS_DIR, args.filter)
    print(f"Found {len(task_dirs)} task directories to re-extract")

    if args.dry_run:
        for td, suite, config in task_dirs:
            print(f"  {suite}/{config}: {td.name}")
        return

    # Load task selection for enrichment
    task_index = None
    if args.selected_tasks.is_file():
        try:
            selection = load_selected_tasks(args.selected_tasks)
            task_index = build_task_index(selection)
        except Exception as e:
            print(f"WARNING: Could not load task selection: {e}", file=sys.stderr)

    # Track stats
    success = 0
    failed = 0
    corrected = 0

    for task_dir, suite, config in task_dirs:
        # Read old metrics for comparison
        old_metrics_path = task_dir / "task_metrics.json"
        old_cost = None
        if old_metrics_path.is_file():
            try:
                old_data = json.loads(old_metrics_path.read_text())
                old_cost = old_data.get("cost_usd")
            except (json.JSONDecodeError, OSError):
                pass

        try:
            tm = process_task_dir(task_dir, suite, config)
            if tm is None:
                failed += 1
                continue

            # Enrich with selection metadata
            if task_index:
                try:
                    enrich_task_metrics(tm, task_index)
                except Exception:
                    pass

            # Write
            out_path = task_dir / "task_metrics.json"
            out_path.write_text(json.dumps(tm.to_dict(), indent=2) + "\n")
            success += 1

            # Check if cost was corrected significantly
            if old_cost is not None and tm.cost_usd is not None:
                if old_cost > 0 and abs(old_cost - tm.cost_usd) / old_cost > 0.1:
                    corrected += 1
                    print(f"  CORRECTED {suite}/{config}/{task_dir.name}: ${old_cost:.2f} -> ${tm.cost_usd:.2f}")
            else:
                # New extraction where there was none before
                reward_str = f"{tm.reward:.2f}" if tm.reward is not None else "n/a"
                print(f"  {suite}/{config}/{task_dir.name}: reward={reward_str} cost=${tm.cost_usd:.2f}" if tm.cost_usd else f"  {suite}/{config}/{task_dir.name}: reward={reward_str} cost=n/a")
        except Exception as e:
            failed += 1
            print(f"  ERROR {suite}/{config}/{task_dir.name}: {e}", file=sys.stderr)

    print(f"\nDone: {success} extracted, {corrected} cost-corrected, {failed} failed")


if __name__ == "__main__":
    main()
