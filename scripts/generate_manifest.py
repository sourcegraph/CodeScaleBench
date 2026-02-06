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

RUNS_DIR = Path(__file__).resolve().parent.parent / "runs" / "official"

# Directories to skip entirely
SKIP_PATTERNS = ["__broken_verifier", "validation_test", "archive"]

# Map on-disk dir prefixes to MANIFEST suite names
DIR_PREFIX_TO_SUITE = {
    "bigcode_mcp_": "ccb_largerepo",
    "codereview_": "ccb_codereview",
    "crossrepo_": "ccb_crossrepo",
    "dibench_": "ccb_dibench",
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

    if exception is not None:
        status = "errored"
        reward_val = 0.0
    elif reward is not None and reward > 0:
        status = "passed"
        reward_val = float(reward)
    else:
        status = "failed"
        reward_val = float(reward) if reward is not None else 0.0

    # Check for trajectory and cost
    has_trajectory = (trial_dir / "agent" / "trajectory.json").exists()
    agent_result = data.get("agent_result") or {}
    has_cost = bool(agent_result.get("n_input_tokens", 0) or agent_result.get("n_output_tokens", 0))

    return {
        "status": status,
        "reward": round(reward_val, 4),
        "has_trajectory": has_trajectory,
        "has_cost": has_cost,
    }


def main():
    if not RUNS_DIR.exists():
        print(f"ERROR: Runs directory not found: {RUNS_DIR}", file=sys.stderr)
        sys.exit(1)

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
            # Merge: later run dirs overwrite earlier ones (sorted order)
            all_tasks[key].update(tasks)

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

        for task_name in sorted(tasks.keys()):
            info = extract_task_info(tasks[task_name])
            task_infos[task_name] = info
            if info["status"] == "passed":
                passed += 1
            elif info["status"] == "errored":
                errored += 1
            else:
                failed += 1
            total_reward += info["reward"]

        task_count = len(task_infos)
        mean_reward = round(total_reward / task_count, 3) if task_count > 0 else 0.0

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

        runs[manifest_key] = {
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
