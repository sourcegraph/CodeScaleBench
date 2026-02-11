#!/usr/bin/env python3
"""
Generate MANIFEST.json from on-disk run results.

Scans runs/official/ for task-level result.json files, groups them by
suite and config, deduplicates by task_name (latest wins), and writes
a canonical MANIFEST.json.
"""

import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = PROJECT_ROOT / "runs" / "official"

# Directories to skip entirely
SKIP_PATTERNS = ["__broken_verifier", "validation_test", "archive"]

# Map on-disk dir prefixes to MANIFEST suite names
DIR_PREFIX_TO_SUITE = {
    "bigcode_mcp_": "ccb_largerepo",
    "codereview_": "ccb_codereview",
    "crossrepo_": "ccb_crossrepo",
    "dependeval_": "ccb_dependeval",
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
}

CONFIGS = ["baseline", "sourcegraph_base", "sourcegraph_full"]


def load_judge_scores(path: Path) -> dict[str, dict]:
    """Load centralized judge_scores.json.

    Returns dict mapping 'benchmark/config/task_id' -> {judge_score, rubric, ...}.
    Returns empty dict if file doesn't exist or is invalid.
    """
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
        return data.get("scores", {})
    except (json.JSONDecodeError, OSError):
        return {}


def should_skip(dirname: str) -> bool:
    for pat in SKIP_PATTERNS:
        if pat in dirname:
            return True
    return False


def detect_suite(dirname: str) -> str | None:
    for prefix, suite in DIR_PREFIX_TO_SUITE.items():
        if dirname.startswith(prefix):
            return suite
    return None


def _parse_started_at(data: dict) -> str:
    """Extract started_at timestamp from result.json for ordering.

    Returns ISO string or empty string if missing.
    """
    return data.get("started_at", "")


def _has_agent_output(data: dict) -> bool:
    """Check if the agent actually produced output (non-zero tokens).

    Zero-token results indicate infrastructure failures (auth errors,
    Docker crashes) where the agent never ran. These should not overwrite
    valid results during dedup.
    """
    agent_result = data.get("agent_result") or {}
    n_input = agent_result.get("n_input_tokens") or 0
    n_output = agent_result.get("n_output_tokens") or 0
    return n_input > 0 or n_output > 0


def scan_config_dir(config_path: Path) -> dict[str, dict]:
    """Scan a config directory (e.g., baseline/) for task-level results.

    Returns dict mapping task_name -> {result_data, trial_dir, timestamp}.
    """
    tasks = {}
    if not config_path.is_dir():
        return tasks

    for batch_dir in sorted(config_path.iterdir()):
        if not batch_dir.is_dir():
            continue
        # Batch dirs are timestamps like 2026-02-03__16-06-16
        # or could be task dirs directly (task_name__hash)
        if "__" in batch_dir.name and not batch_dir.name.startswith("20"):
            # This looks like a direct task dir (task_name__hash)
            result_file = batch_dir / "result.json"
            if result_file.exists():
                try:
                    data = json.loads(result_file.read_text())
                    task_name = data.get("task_name", batch_dir.name.rsplit("__", 1)[0])
                    task_name = _normalize_task_name(task_name)
                    tasks[task_name] = {
                        "data": data,
                        "trial_dir": batch_dir,
                        "batch_dir": config_path,
                    }
                except (json.JSONDecodeError, KeyError):
                    pass
        else:
            # Timestamp batch dir - look for task dirs inside
            for trial_dir in sorted(batch_dir.iterdir()):
                if not trial_dir.is_dir():
                    continue
                # Skip dirs that look like timestamps (batch metadata)
                if trial_dir.name.startswith("20"):
                    continue
                result_file = trial_dir / "result.json"
                if result_file.exists():
                    try:
                        data = json.loads(result_file.read_text())
                        task_name = data.get("task_name", trial_dir.name.rsplit("__", 1)[0])
                        task_name = _normalize_task_name(task_name)
                        # Latest wins (sorted order = latest batch dir last)
                        tasks[task_name] = {
                            "data": data,
                            "trial_dir": trial_dir,
                            "batch_dir": batch_dir,
                        }
                    except (json.JSONDecodeError, KeyError):
                        pass
    return tasks


def extract_task_info(task_entry: dict) -> dict:
    """Extract MANIFEST-format task info from a result.json."""
    data = task_entry["data"]
    trial_dir = task_entry["trial_dir"]

    # Determine status
    exception = data.get("exception_info")
    verifier = data.get("verifier_result") or {}
    rewards = verifier.get("rewards") or {}
    reward = rewards.get("reward")

    # Check for trajectory and cost
    has_trajectory = (trial_dir / "agent" / "trajectory.json").exists()
    agent_result = data.get("agent_result") or {}
    has_cost = bool(agent_result.get("n_input_tokens", 0) or agent_result.get("n_output_tokens", 0))

    # Detect infrastructure failures where the agent never ran
    n_input = agent_result.get("n_input_tokens")
    n_output = agent_result.get("n_output_tokens")
    # Auth failures: tokens are explicitly 0 (agent started but auth failed)
    zero_token = (n_input == 0 and n_output == 0)
    # Crash failures: tokens are null, no trajectory, verifier saw nothing useful,
    # AND the agent trace is tiny (<=5 lines). This distinguishes true crashes
    # (protonmail Node v16, openlibrary setup fail) from H3 token-logging bugs
    # where the agent ran fine but tokens weren't recorded.
    crash_failure = False
    if (
        n_input is None
        and n_output is None
        and not has_trajectory
        and (reward is None or reward == 0)
    ):
        cc_path = trial_dir / "agent" / "claude-code.txt"
        cc_lines = 0
        if cc_path.exists():
            with open(cc_path) as f:
                for i, _ in enumerate(f, 1):
                    if i > 5:
                        break
                cc_lines = i
        crash_failure = cc_lines <= 5

    if exception is not None:
        status = "errored"
        reward_val = 0.0
    elif zero_token or crash_failure:
        status = "errored"
        reward_val = 0.0
    elif reward is not None and reward > 0:
        status = "passed"
        reward_val = float(reward)
    else:
        status = "failed"
        reward_val = float(reward) if reward is not None else 0.0

    info = {
        "status": status,
        "reward": round(reward_val, 4),
        "has_trajectory": has_trajectory,
        "has_cost": has_cost,
    }

    # LLM Judge score from judge_result.json alongside result.json
    judge_path = trial_dir / "judge_result.json"
    if judge_path.is_file():
        try:
            jdata = json.loads(judge_path.read_text())
            js = jdata.get("judge_score")
            if js is not None:
                info["judge_score"] = round(float(js), 4)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            pass

    return info


def _normalize_task_name(name: str) -> str:
    """Normalize task name for matching across naming conventions.

    Handles the dash-vs-underscore discrepancy in SWE-bench Pro task names:
    - Selection JSON uses: instance_protonmail__webclients-HASH (double underscore)
    - Some result.json uses: instance_protonmail-webclients-HASH (single dash)

    Strategy: for 'instance_ORG__REPO-HASH' pattern, normalize ORG__REPO to ORG__REPO
    by replacing the first single-dash separator after 'instance_' with '__'.
    """
    if not name.startswith("instance_"):
        return name
    # Already uses __ separator — canonical form
    if "__" in name[len("instance_"):]:
        return name
    # Convert first dash after 'instance_' to '__'
    # e.g. instance_nodebb-nodebb-HASH -> instance_nodebb__nodebb-HASH
    suffix = name[len("instance_"):]
    dash_pos = suffix.find("-")
    if dash_pos > 0:
        return "instance_" + suffix[:dash_pos] + "__" + suffix[dash_pos + 1:]
    return name


def load_selected_tasks(path: Path) -> dict[str, set[str]]:
    """Load selected_benchmark_tasks.json and return {suite: {task_name, ...}}.

    Used to filter MANIFEST to only include selected tasks, removing extras
    from old batches (e.g. PyTorch sgt-007/017/024, SWE-Pro gap-fill originals).

    Handles naming convention differences:
    - Selection may use 'ccb_dibench-foo' but result.json uses 'dibench-foo'
    - Selection may use 'instance_org__repo-hash' but result.json uses 'instance_org-repo-hash'
    Both forms are added to the allowed set.
    """
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
        tasks_list = data.get("tasks", data) if isinstance(data, dict) else data
        result: dict[str, set[str]] = defaultdict(set)
        for t in tasks_list:
            suite = t.get("benchmark", t.get("suite", ""))
            if not suite.startswith("ccb_"):
                suite = "ccb_" + suite
            task_name = t.get("task_name", t.get("task_id", ""))
            if suite and task_name:
                normalized = _normalize_task_name(task_name)
                result[suite].add(normalized)
                # Also add without ccb_ suite prefix (e.g. ccb_dibench-foo -> dibench-foo)
                # because result.json often omits the ccb_ prefix
                if normalized.startswith("ccb_"):
                    result[suite].add(normalized[4:])
                # Also add with ccb_ prefix for the reverse case
                if not normalized.startswith("ccb_"):
                    result[suite].add("ccb_" + normalized)
        return dict(result)
    except (json.JSONDecodeError, OSError):
        return {}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate MANIFEST.json from on-disk run results.")
    parser.add_argument(
        "--judge-scores",
        type=Path,
        default=PROJECT_ROOT / "judge_scores.json",
        help="Path to centralized judge_scores.json (default: ./judge_scores.json)",
    )
    parser.add_argument(
        "--selected-only",
        action="store_true",
        default=True,
        help="Filter to only tasks in selected_benchmark_tasks.json (default: True)",
    )
    parser.add_argument(
        "--no-selected-filter",
        action="store_true",
        help="Disable filtering — include all tasks found on disk",
    )
    cli_args = parser.parse_args()
    if cli_args.no_selected_filter:
        cli_args.selected_only = False

    if not RUNS_DIR.exists():
        print(f"ERROR: Runs directory not found: {RUNS_DIR}", file=sys.stderr)
        sys.exit(1)

    judge_scores = load_judge_scores(cli_args.judge_scores)

    # Collect all tasks grouped by (suite, config)
    # Structure: {(suite, config): {task_name: task_entry}}
    all_tasks: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)

    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        if should_skip(run_dir.name):
            continue

        suite = detect_suite(run_dir.name)
        if suite is None:
            continue

        for config in CONFIGS:
            config_path = run_dir / config
            if not config_path.exists():
                continue

            tasks = scan_config_dir(config_path)
            key = (suite, config)
            # Merge: for each task, keep the result with the latest started_at
            # timestamp. This handles cases where run dir names don't sort
            # chronologically (e.g., "rerun" < "selected" alphabetically but
            # the rerun is actually newer).
            for task_name, task_entry in tasks.items():
                existing = all_tasks[key].get(task_name)
                if existing is None:
                    all_tasks[key][task_name] = task_entry
                else:
                    new_has_output = _has_agent_output(task_entry["data"])
                    old_has_output = _has_agent_output(existing["data"])
                    if new_has_output and not old_has_output:
                        # New result has agent output, old doesn't — prefer new
                        all_tasks[key][task_name] = task_entry
                    elif not new_has_output and old_has_output:
                        # Old result has agent output, new doesn't — keep old
                        pass
                    else:
                        # Both have or both lack output — use timestamp
                        new_ts = _parse_started_at(task_entry["data"])
                        old_ts = _parse_started_at(existing["data"])
                        if new_ts >= old_ts:
                            all_tasks[key][task_name] = task_entry

    # Filter to selected tasks only (removes extras from old batches)
    selected_tasks = {}
    if cli_args.selected_only:
        selection_path = PROJECT_ROOT / "configs" / "selected_benchmark_tasks.json"
        selected_tasks = load_selected_tasks(selection_path)
        if selected_tasks:
            filtered_count = 0
            for key in list(all_tasks.keys()):
                suite, config = key
                allowed = selected_tasks.get(suite)
                if allowed is None:
                    # Suite not in selection file — keep all (might be new benchmark)
                    continue
                before = len(all_tasks[key])
                all_tasks[key] = {
                    tn: te for tn, te in all_tasks[key].items()
                    if _normalize_task_name(tn) in allowed
                }
                removed = before - len(all_tasks[key])
                if removed:
                    filtered_count += removed
            if filtered_count:
                print(f"  Filtered out {filtered_count} tasks not in selected_benchmark_tasks.json")

    # Build MANIFEST
    runs = {}
    total_tasks = 0

    for (suite, config), tasks in sorted(all_tasks.items()):
        if not tasks:
            continue

        manifest_key = f"{suite}/{config}"
        task_infos = {}
        passed = 0
        failed = 0
        errored = 0
        total_reward = 0.0

        judge_score_sum = 0.0
        judge_count = 0

        for task_name in sorted(tasks.keys()):
            info = extract_task_info(tasks[task_name])

            # Merge judge score from centralized index (if not already from judge_result.json)
            if "judge_score" not in info:
                judge_key = f"{suite}/{config}/{task_name}"
                judge_entry = judge_scores.get(judge_key)
                if judge_entry and "judge_score" in judge_entry:
                    info["judge_score"] = round(float(judge_entry["judge_score"]), 4)

            task_infos[task_name] = info
            if info["status"] == "passed":
                passed += 1
            elif info["status"] == "errored":
                errored += 1
            else:
                failed += 1
            # Exclude errored tasks from mean reward (infra failures, not agent failures)
            if info["status"] != "errored":
                total_reward += info["reward"]

            if "judge_score" in info:
                judge_score_sum += info["judge_score"]
                judge_count += 1

        task_count = len(task_infos)
        scored_count = task_count - errored
        mean_reward = round(total_reward / scored_count, 3) if scored_count > 0 else 0.0
        mean_judge_score = round(judge_score_sum / judge_count, 3) if judge_count > 0 else None

        # Extract timestamp from first task's data
        first_task = next(iter(tasks.values()))
        timestamp = first_task["data"].get("started_at", "")
        if timestamp:
            # Normalize timestamp format
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                timestamp = dt.strftime("%Y-%m-%d %H-%M-%S")
            except (ValueError, AttributeError):
                pass

        run_entry = {
            "run_id": manifest_key.replace("/", "_"),
            "model": "anthropic/claude-opus-4-5-20251101",
            "timestamp": timestamp,
            "task_count": task_count,
            "passed": passed,
            "failed": failed,
            "errored": errored,
            "mean_reward": mean_reward,
            "tasks": task_infos,
        }
        if mean_judge_score is not None:
            run_entry["mean_judge_score"] = mean_judge_score
            run_entry["judge_count"] = judge_count
        runs[manifest_key] = run_entry
        total_tasks += task_count

    manifest = {
        "description": "Canonical run manifest for CodeContextBench evaluation",
        "generated": datetime.now(timezone.utc).isoformat(),
        "total_tasks": total_tasks,
        "total_runs": len(runs),
        "runs": runs,
    }

    output_path = RUNS_DIR / "MANIFEST.json"
    with open(output_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"MANIFEST generated: {output_path}")
    print(f"  Total runs: {len(runs)}")
    print(f"  Total tasks: {total_tasks}")
    print()
    for key, run in runs.items():
        print(f"  {key:45s}  tasks={run['task_count']:>3d}  passed={run['passed']:>3d}  failed={run['failed']:>3d}  errored={run['errored']:>3d}  mean_reward={run['mean_reward']:.3f}")


if __name__ == "__main__":
    main()
