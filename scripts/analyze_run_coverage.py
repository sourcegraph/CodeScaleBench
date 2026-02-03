#!/usr/bin/env python3
"""
Analyze which curated benchmark tasks have been completed across different config modes.

Compares the 125-task curated list (selected_benchmark_tasks.json) against actual
completed runs in runs/official/ to identify gaps.
"""

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

BASE_DIR = Path("/home/stephanie_jarmak/CodeContextBench")
SELECTED_TASKS_FILE = BASE_DIR / "configs" / "selected_benchmark_tasks.json"
RUNS_DIR = BASE_DIR / "runs" / "official"


def load_curated_tasks():
    """Load the 125 curated task IDs grouped by benchmark."""
    with open(SELECTED_TASKS_FILE) as f:
        data = json.load(f)

    by_benchmark = defaultdict(list)
    for task in data["tasks"]:
        by_benchmark[task["benchmark"]].append(task["task_id"])
    return by_benchmark


def extract_task_name_from_trial(trial_dir):
    """
    Extract the canonical task name from a trial directory by reading its config.json.
    Returns the task name derived from the task path in config.
    """
    config_path = os.path.join(trial_dir, "config.json")
    if not os.path.isfile(config_path):
        return None
    try:
        with open(config_path) as f:
            cfg = json.load(f)
        task_path = cfg.get("task", {}).get("path", "")
        source = cfg.get("task", {}).get("source", "")

        if source == "swebenchpro":
            # Path like: datasets/swebenchpro/instance_ansible__ansible-4c5ce5...
            # The last component is the full task instance ID
            return task_path.split("/")[-1]
        else:
            # For locobench and others, the last path component is the task name
            return task_path.rstrip("/").split("/")[-1]
    except (json.JSONDecodeError, KeyError):
        return None


def find_completed_tasks_in_run(run_dir):
    """
    Scan a run directory for completed tasks (those with task_metrics.json).
    Returns dict: {config_mode: set_of_task_names}
    """
    completed = defaultdict(set)

    if not os.path.isdir(run_dir):
        return completed

    for config_mode in os.listdir(run_dir):
        config_path = os.path.join(run_dir, config_mode)
        if not os.path.isdir(config_path):
            continue
        if config_mode in ("archive",):
            continue

        # Walk through timestamped run dirs or direct trial dirs
        for entry in os.listdir(config_path):
            entry_path = os.path.join(config_path, entry)
            if not os.path.isdir(entry_path):
                continue

            # Check if this is a timestamped run dir (contains trial subdirs)
            # or a direct trial dir (contains task_metrics.json)
            if os.path.isfile(os.path.join(entry_path, "task_metrics.json")):
                # This is a direct trial dir
                task_name = extract_task_name_from_trial(entry_path)
                if task_name:
                    completed[config_mode].add(task_name)
            else:
                # This might be a timestamped run dir containing trial subdirs
                # First check if it has a result.json (indicating it's a Harbor run dir)
                if os.path.isfile(os.path.join(entry_path, "result.json")):
                    # This is a Harbor run dir - look for trial subdirs
                    for trial_entry in os.listdir(entry_path):
                        trial_path = os.path.join(entry_path, trial_entry)
                        if os.path.isdir(trial_path) and os.path.isfile(
                            os.path.join(trial_path, "task_metrics.json")
                        ):
                            task_name = extract_task_name_from_trial(trial_path)
                            if task_name:
                                completed[config_mode].add(task_name)

    return completed


def match_task_id_to_completed(task_id, completed_set, benchmark):
    """
    Check if a curated task_id has a match in the completed set.
    Handles naming differences between selected_benchmark_tasks.json and actual runs.
    """
    # Direct match
    if task_id in completed_set:
        return True

    # For swebenchpro, the task_id in the selection file uses double underscores
    # between owner and repo (e.g. instance_nodebb__nodebb-...) while the
    # dataset path may vary. Try matching on the commit hash portion.
    if benchmark == "ccb_swebenchpro":
        # Extract the key part: everything after "instance_"
        for completed_name in completed_set:
            if task_id == completed_name:
                return True
            # Try matching by extracting the commit hash
            # task_id format: instance_owner__repo-commitsha-vsha
            # completed format should be the same from config.json extraction
            # But let's also try fuzzy: match if one starts with the other's prefix
            tid_parts = task_id.split("-")
            cid_parts = completed_name.split("-")
            # Match on the first N significant characters
            if len(tid_parts) >= 2 and len(cid_parts) >= 2:
                # Compare owner__repo portion and first 8 chars of commit
                tid_prefix = "-".join(tid_parts[:2])[:50]
                cid_prefix = "-".join(cid_parts[:2])[:50]
                if tid_prefix == cid_prefix:
                    # Further verify with more of the string
                    if task_id[:60] == completed_name[:60]:
                        return True

    return False


def detect_benchmark_from_run_dir(run_dir_name):
    """Infer benchmark name from run directory name."""
    if "locobench" in run_dir_name:
        return "ccb_locobench"
    elif "swebenchpro" in run_dir_name:
        return "ccb_swebenchpro"
    elif "pytorch" in run_dir_name:
        return "ccb_pytorch"
    elif "largerepo" in run_dir_name:
        return "ccb_largerepo"
    elif "k8sdocs" in run_dir_name:
        return "ccb_k8sdocs"
    elif "tac" in run_dir_name:
        return "ccb_tac"
    elif "dependeval" in run_dir_name:
        return "ccb_dependeval"
    elif "sweperf" in run_dir_name:
        return "ccb_sweperf"
    elif "repoqa" in run_dir_name:
        return "ccb_repoqa"
    elif "crossrepo" in run_dir_name:
        return "ccb_crossrepo"
    elif "dibench" in run_dir_name:
        return "ccb_dibench"
    return None


def main():
    # Load curated tasks
    curated = load_curated_tasks()
    total_curated = sum(len(v) for v in curated.values())
    print(f"Loaded {total_curated} curated tasks across {len(curated)} benchmarks\n")

    # Scan all active runs (not archive)
    # completed_by_benchmark[benchmark][config_mode] = set of task names
    completed_by_benchmark = defaultdict(lambda: defaultdict(set))

    run_dirs = []
    for entry in os.listdir(RUNS_DIR):
        if entry == "archive" or not os.path.isdir(RUNS_DIR / entry):
            continue
        if entry.endswith(".log"):
            continue
        run_dirs.append(entry)

    print(f"Found {len(run_dirs)} active run directories:")
    for rd in sorted(run_dirs):
        benchmark = detect_benchmark_from_run_dir(rd)
        print(f"  {rd} -> {benchmark}")
        if benchmark is None:
            print(f"    WARNING: Could not detect benchmark from run dir name")
            continue

        completed = find_completed_tasks_in_run(RUNS_DIR / rd)
        for config_mode, task_set in completed.items():
            completed_by_benchmark[benchmark][config_mode] |= task_set
            print(f"    {config_mode}: {len(task_set)} completed tasks")

    print()

    # Print summary of all completed tasks per benchmark/config
    print("=" * 100)
    print("COMPLETED TASKS SUMMARY")
    print("=" * 100)
    for benchmark in sorted(completed_by_benchmark):
        print(f"\n{benchmark}:")
        for config_mode in sorted(completed_by_benchmark[benchmark]):
            tasks = completed_by_benchmark[benchmark][config_mode]
            print(f"  {config_mode}: {len(tasks)} tasks")

    # Compare against curated list
    print("\n" + "=" * 100)
    print("COVERAGE ANALYSIS: CURATED TASKS vs COMPLETED RUNS")
    print("=" * 100)

    config_modes_of_interest = ["baseline", "sourcegraph_full"]

    grand_total = {
        "curated": 0,
        "both_complete": 0,
        "baseline_only": 0,
        "hybrid_only": 0,
        "neither": 0,
    }

    for benchmark in sorted(curated.keys()):
        task_ids = curated[benchmark]
        baseline_set = completed_by_benchmark.get(benchmark, {}).get("baseline", set())
        hybrid_set = completed_by_benchmark.get(benchmark, {}).get(
            "sourcegraph_full", set()
        )

        both_complete = []
        baseline_only = []
        hybrid_only = []
        neither = []

        for tid in task_ids:
            has_baseline = match_task_id_to_completed(tid, baseline_set, benchmark)
            has_hybrid = match_task_id_to_completed(tid, hybrid_set, benchmark)

            if has_baseline and has_hybrid:
                both_complete.append(tid)
            elif has_baseline:
                baseline_only.append(tid)
            elif has_hybrid:
                hybrid_only.append(tid)
            else:
                neither.append(tid)

        print(f"\n{'─' * 100}")
        print(f"  {benchmark}  ({len(task_ids)} curated tasks)")
        print(f"{'─' * 100}")
        print(f"  Both complete:          {len(both_complete):3d} / {len(task_ids)}")
        print(f"  Baseline only:          {len(baseline_only):3d} / {len(task_ids)}")
        print(f"  Sourcegraph hybrid only:{len(hybrid_only):3d} / {len(task_ids)}")
        print(f"  Neither complete:       {len(neither):3d} / {len(task_ids)}")

        if baseline_only:
            print(f"\n  NEEDS sourcegraph_full ({len(baseline_only)}):")
            for tid in baseline_only:
                print(f"    - {tid}")

        if hybrid_only:
            print(f"\n  NEEDS baseline ({len(hybrid_only)}):")
            for tid in hybrid_only:
                print(f"    - {tid}")

        if neither:
            print(f"\n  NEEDS BOTH baseline AND sourcegraph_full ({len(neither)}):")
            for tid in neither:
                print(f"    - {tid}")

        grand_total["curated"] += len(task_ids)
        grand_total["both_complete"] += len(both_complete)
        grand_total["baseline_only"] += len(baseline_only)
        grand_total["hybrid_only"] += len(hybrid_only)
        grand_total["neither"] += len(neither)

    # Grand total summary
    print(f"\n{'=' * 100}")
    print("GRAND TOTAL SUMMARY")
    print(f"{'=' * 100}")
    print(f"  Total curated tasks:        {grand_total['curated']:3d}")
    print(f"  Both configs complete:      {grand_total['both_complete']:3d}  ({100*grand_total['both_complete']/grand_total['curated']:.1f}%)")
    print(f"  Baseline only:              {grand_total['baseline_only']:3d}  ({100*grand_total['baseline_only']/grand_total['curated']:.1f}%)")
    print(f"  Sourcegraph hybrid only:    {grand_total['hybrid_only']:3d}  ({100*grand_total['hybrid_only']/grand_total['curated']:.1f}%)")
    print(f"  Neither complete:           {grand_total['neither']:3d}  ({100*grand_total['neither']/grand_total['curated']:.1f}%)")
    print()
    print(f"  Tasks needing baseline run:          {grand_total['hybrid_only'] + grand_total['neither']:3d}")
    print(f"  Tasks needing sourcegraph_full run:{grand_total['baseline_only'] + grand_total['neither']:3d}")
    print(f"  Tasks needing ANY run:               {grand_total['baseline_only'] + grand_total['hybrid_only'] + grand_total['neither']:3d}")

    # Check for sourcegraph_base runs
    has_base = False
    for benchmark in completed_by_benchmark:
        if "sourcegraph_base" in completed_by_benchmark[benchmark]:
            has_base = True
            break
    if has_base:
        print(f"\n{'=' * 100}")
        print("NOTE: sourcegraph_base runs also found:")
        for benchmark in sorted(completed_by_benchmark):
            nds = completed_by_benchmark[benchmark].get("sourcegraph_base", set())
            if nds:
                print(f"  {benchmark}: {len(nds)} tasks")


if __name__ == "__main__":
    main()
