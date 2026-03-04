#!/usr/bin/env python3
"""
Find MCP-distracted tasks in SDLC staging runs.

Scans all *_sonnet_* run directories under runs/staging/ for tasks that have
both baseline and sourcegraph_full results, then identifies tasks where
SG_full reward is significantly lower than baseline (delta < -0.10).

Also separately lists code-review tasks that need reruns.
"""

import json
from pathlib import Path
from collections import defaultdict

STAGING_DIR = Path(__file__).resolve().parent.parent / "runs" / "staging"

SDLC_SUITES = {"build", "feature", "refactor", "debug", "design", "document", "fix", "secure", "test", "understand"}


def extract_suite_from_dir(run_dir_name):
    for suite in SDLC_SUITES:
        if run_dir_name.startswith(f"{suite}_"):
            return suite
    return None


def extract_reward_from_batch_result(result_path):
    """Extract reward from a batch-level result.json using stats.evals.*.reward_stats."""
    try:
        data = json.loads(result_path.read_text())
        stats = data.get("stats", {}).get("evals", {})
        for eval_key, eval_data in stats.items():
            reward_stats = eval_data.get("reward_stats", {})
            for reward_key in ("reward", "score"):
                if reward_key in reward_stats:
                    for val_str, trials in reward_stats[reward_key].items():
                        return float(val_str)
            metrics = eval_data.get("metrics", [])
            if metrics:
                return metrics[0].get("mean")
    except Exception:
        pass
    return None


def extract_reward_from_trial_result(result_path):
    """Extract reward from a trial-level result.json via verifier_result.rewards."""
    try:
        data = json.loads(result_path.read_text())
        vr = data.get("verifier_result", {})
        rewards = vr.get("rewards", {})
        for key in ("reward", "score"):
            if key in rewards:
                return float(rewards[key])
    except Exception:
        pass
    return None


def get_task_name_from_dir(task_dir_name):
    """Extract canonical task name from dir like ccb_build_bustub-hyperloglog-impl-001_baseline."""
    name = task_dir_name
    for suite in SDLC_SUITES:
        # Try new naming first, then legacy
        for fmt in (f"csb_sdlc_{suite}_", f"ccb_{suite}_"):
            if name.startswith(fmt):
                name = name[len(fmt):]
                break
        else:
            continue
        break

    for suffix in ("_sourcegraph_full", "_baseline"):
        if name.endswith(suffix):
            name = name[:-len(suffix)]
            break

    return name


def get_reward_for_task_dir(task_dir):
    """Get reward from a task directory, trying batch-level then trial-level result.json."""
    batch_result = task_dir / "result.json"
    if batch_result.exists():
        reward = extract_reward_from_batch_result(batch_result)
        if reward is not None:
            return reward

    for child in task_dir.iterdir():
        if child.is_dir() and "__" in child.name:
            trial_result = child / "result.json"
            if trial_result.exists():
                reward = extract_reward_from_trial_result(trial_result)
                if reward is not None:
                    return reward

    return None


def check_is_errored(task_dir):
    """Check if a task errored (has error in result.json stats)."""
    batch_result = task_dir / "result.json"
    if batch_result.exists():
        try:
            data = json.loads(batch_result.read_text())
            stats = data.get("stats", {})
            if stats.get("n_errors", 0) > 0:
                return True
        except Exception:
            pass
    return False


def main():
    all_results = defaultdict(lambda: {"baseline": None, "sgfull": None, "suite": None,
                                        "bl_run": None, "sg_run": None,
                                        "bl_errored": False, "sg_errored": False})

    run_dirs = sorted(STAGING_DIR.iterdir())

    for run_dir in run_dirs:
        if not run_dir.is_dir():
            continue
        if "sonnet" not in run_dir.name:
            continue
        if "archive" in run_dir.name:
            continue

        suite = extract_suite_from_dir(run_dir.name)
        if suite is None:
            continue

        # Process baseline
        bl_dir = run_dir / "baseline"
        if bl_dir.is_dir():
            for task_entry in bl_dir.iterdir():
                if not task_entry.is_dir():
                    continue
                if task_entry.name == "archive":
                    continue
                if not task_entry.name.startswith(("ccb_", "csb_")):
                    continue

                task_name = get_task_name_from_dir(task_entry.name)
                reward = get_reward_for_task_dir(task_entry)
                errored = check_is_errored(task_entry)

                key = (suite, task_name)
                if reward is not None:
                    all_results[key]["baseline"] = reward
                    all_results[key]["suite"] = suite
                    all_results[key]["bl_run"] = run_dir.name
                    all_results[key]["bl_errored"] = errored
                elif errored:
                    if all_results[key]["baseline"] is None:
                        all_results[key]["suite"] = suite
                        all_results[key]["bl_run"] = run_dir.name
                        all_results[key]["bl_errored"] = True

        # Process sourcegraph_full
        sg_dir = run_dir / "sourcegraph_full"
        if sg_dir.is_dir():
            for task_entry in sg_dir.iterdir():
                if not task_entry.is_dir():
                    continue
                if task_entry.name == "archive":
                    continue
                if not task_entry.name.startswith(("ccb_", "csb_")):
                    continue

                task_name = get_task_name_from_dir(task_entry.name)
                reward = get_reward_for_task_dir(task_entry)
                errored = check_is_errored(task_entry)

                key = (suite, task_name)
                if reward is not None:
                    all_results[key]["sgfull"] = reward
                    all_results[key]["suite"] = suite
                    all_results[key]["sg_run"] = run_dir.name
                    all_results[key]["sg_errored"] = errored
                elif errored:
                    if all_results[key]["sgfull"] is None:
                        all_results[key]["suite"] = suite
                        all_results[key]["sg_run"] = run_dir.name
                        all_results[key]["sg_errored"] = True

    # =========================================================================
    # Report 1: Summary stats
    # =========================================================================
    paired = {k: v for k, v in all_results.items()
              if v["baseline"] is not None and v["sgfull"] is not None}

    print("=" * 100)
    print("SDLC STAGING RUN ANALYSIS")
    print("=" * 100)
    print(f"\nTotal unique tasks found:     {len(all_results)}")
    print(f"Tasks with baseline result:   {sum(1 for v in all_results.values() if v['baseline'] is not None)}")
    print(f"Tasks with SG_full result:    {sum(1 for v in all_results.values() if v['sgfull'] is not None)}")
    print(f"Tasks with BOTH (paired):     {len(paired)}")

    # Per-suite summary
    print(f"\n{'Suite':<12} {'Paired':>6} {'BL Only':>7} {'SG Only':>7} {'Neither':>8}  {'Avg BL':>7} {'Avg SG':>7} {'Avg D':>7}")
    print("-" * 80)
    for suite in sorted(SDLC_SUITES):
        suite_tasks = {k: v for k, v in all_results.items() if v["suite"] == suite}
        n_paired = sum(1 for v in suite_tasks.values() if v["baseline"] is not None and v["sgfull"] is not None)
        n_bl_only = sum(1 for v in suite_tasks.values() if v["baseline"] is not None and v["sgfull"] is None)
        n_sg_only = sum(1 for v in suite_tasks.values() if v["baseline"] is None and v["sgfull"] is not None)
        n_neither = sum(1 for v in suite_tasks.values() if v["baseline"] is None and v["sgfull"] is None)

        paired_tasks = {k: v for k, v in suite_tasks.items() if v["baseline"] is not None and v["sgfull"] is not None}
        if paired_tasks:
            avg_bl = sum(v["baseline"] for v in paired_tasks.values()) / len(paired_tasks)
            avg_sg = sum(v["sgfull"] for v in paired_tasks.values()) / len(paired_tasks)
            avg_delta = avg_sg - avg_bl
            print(f"{suite:<12} {n_paired:>6} {n_bl_only:>7} {n_sg_only:>7} {n_neither:>8}  {avg_bl:>7.3f} {avg_sg:>7.3f} {avg_delta:>+7.3f}")
        else:
            print(f"{suite:<12} {n_paired:>6} {n_bl_only:>7} {n_sg_only:>7} {n_neither:>8}  {'N/A':>7} {'N/A':>7} {'N/A':>7}")

    # =========================================================================
    # Report 2: MCP-distracted tasks (SG_full reward < baseline by > 0.10)
    # =========================================================================
    distracted = []
    for (suite, task_name), v in paired.items():
        delta = v["sgfull"] - v["baseline"]
        if delta < -0.10:
            distracted.append({
                "suite": suite,
                "task": task_name,
                "bl_reward": v["baseline"],
                "sg_reward": v["sgfull"],
                "delta": delta,
                "bl_run": v["bl_run"],
                "sg_run": v["sg_run"],
            })

    distracted.sort(key=lambda x: x["delta"])

    print(f"\n\n{'=' * 100}")
    print(f"MCP-DISTRACTED TASKS (SG_full reward < baseline, delta < -0.10)")
    print(f"{'=' * 100}")
    print(f"\nFound {len(distracted)} distracted tasks out of {len(paired)} paired tasks\n")

    if distracted:
        print(f"{'Suite':<12} {'Task':<50} {'BL':>6} {'SG':>6} {'Delta':>7}")
        print("-" * 85)
        for t in distracted:
            print(f"{t['suite']:<12} {t['task']:<50} {t['bl_reward']:>6.3f} {t['sg_reward']:>6.3f} {t['delta']:>+7.3f}")

        print(f"\nRun sources for distracted tasks:")
        print(f"{'Task':<50} {'BL Run':<55} {'SG Run'}")
        print("-" * 160)
        for t in distracted:
            print(f"{t['task']:<50} {t['bl_run']:<55} {t['sg_run']}")
    else:
        print("  No MCP-distracted tasks found.")

    # =========================================================================
    # Report 3: All paired results (sorted by delta)
    # =========================================================================
    all_paired_sorted = []
    for (suite, task_name), v in paired.items():
        delta = v["sgfull"] - v["baseline"]
        all_paired_sorted.append({
            "suite": suite,
            "task": task_name,
            "bl_reward": v["baseline"],
            "sg_reward": v["sgfull"],
            "delta": delta,
        })
    all_paired_sorted.sort(key=lambda x: x["delta"])

    print(f"\n\n{'=' * 100}")
    print(f"ALL PAIRED RESULTS (sorted by delta, worst first)")
    print(f"{'=' * 100}\n")
    print(f"{'Suite':<12} {'Task':<50} {'BL':>6} {'SG':>6} {'Delta':>7}")
    print("-" * 85)
    for t in all_paired_sorted:
        marker = " <-- DISTRACTED" if t["delta"] < -0.10 else ""
        print(f"{t['suite']:<12} {t['task']:<50} {t['bl_reward']:>6.3f} {t['sg_reward']:>6.3f} {t['delta']:>+7.3f}{marker}")

    # =========================================================================
    # Report 4: Code review tasks
    # =========================================================================
    print(f"\n\n{'=' * 100}")
    print(f"CODE REVIEW TASKS (known Dockerfile bug, need reruns)")
    print(f"{'=' * 100}\n")

    code_review_tasks = {}
    for (suite, task_name), v in all_results.items():
        if "code-review" in task_name.lower():
            code_review_tasks[(suite, task_name)] = v

    if code_review_tasks:
        print(f"Found {len(code_review_tasks)} code-review tasks\n")
        print(f"{'Suite':<12} {'Task':<50} {'BL':>6} {'SG':>6} {'BL Err':>6} {'SG Err':>6}")
        print("-" * 90)
        for (suite, task_name), v in sorted(code_review_tasks.items()):
            bl_str = f"{v['baseline']:.3f}" if v['baseline'] is not None else "N/A"
            sg_str = f"{v['sgfull']:.3f}" if v['sgfull'] is not None else "N/A"
            bl_err = "ERR" if v['bl_errored'] else ""
            sg_err = "ERR" if v['sg_errored'] else ""
            print(f"{suite:<12} {task_name:<50} {bl_str:>6} {sg_str:>6} {bl_err:>6} {sg_err:>6}")
    else:
        print("  No code-review tasks found in staging runs.")

    # =========================================================================
    # Report 5: Tasks with errors (no valid result)
    # =========================================================================
    errored_tasks = []
    for (suite, task_name), v in all_results.items():
        bl_err = v["baseline"] is None and v["bl_errored"]
        sg_err = v["sgfull"] is None and v["sg_errored"]
        if bl_err or sg_err:
            errored_tasks.append({
                "suite": suite,
                "task": task_name,
                "bl_errored": bl_err,
                "sg_errored": sg_err,
                "bl_reward": v["baseline"],
                "sg_reward": v["sgfull"],
            })

    if errored_tasks:
        errored_tasks.sort(key=lambda x: (x["suite"], x["task"]))
        print(f"\n\n{'=' * 100}")
        print(f"TASKS WITH ERRORS (no valid result in at least one config)")
        print(f"{'=' * 100}\n")
        print(f"Found {len(errored_tasks)} tasks with errors\n")
        print(f"{'Suite':<12} {'Task':<50} {'BL':>8} {'SG':>8}")
        print("-" * 82)
        for t in errored_tasks:
            bl_str = f"{t['bl_reward']:.3f}" if t['bl_reward'] is not None else ("ERROR" if t['bl_errored'] else "NONE")
            sg_str = f"{t['sg_reward']:.3f}" if t['sg_reward'] is not None else ("ERROR" if t['sg_errored'] else "NONE")
            print(f"{t['suite']:<12} {t['task']:<50} {bl_str:>8} {sg_str:>8}")


if __name__ == "__main__":
    main()
