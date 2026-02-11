#!/usr/bin/env python3
"""Retroactively generate trajectory.json for tasks affected by the H3 bug.

The H3 bug: Harbor's _get_session_dir returns None when Claude Code spawns
subagents (via the Task tool), because subagent JSONL files create multiple
candidate directories. This prevents trajectory.json from being written
during populate_context_post_run.

This script:
1. Scans all trial directories for missing trajectory.json
2. Identifies tasks with the H3 pattern (main session + subagent dirs)
3. Uses Harbor's ClaudeCode._convert_events_to_trajectory to generate
   trajectory.json from the main session JSONL

Usage:
    python3 scripts/repair_h3_trajectories.py              # Dry run
    python3 scripts/repair_h3_trajectories.py --apply       # Actually write files
    python3 scripts/repair_h3_trajectories.py --apply -v    # Verbose
"""

import argparse
import glob
import json
import os
import sys
from pathlib import Path


def find_h3_tasks(base_dir: str, verbose: bool = False) -> list[dict]:
    """Find all trial directories affected by the H3 bug."""
    affected = []

    for batch_dir in sorted(glob.glob(f"{base_dir}/*/")):
        batch_name = os.path.basename(batch_dir.rstrip("/"))
        if batch_name in ("archive", "MANIFEST.json"):
            continue

        for config_dir in glob.glob(f"{batch_dir}/*/"):
            config_name = os.path.basename(config_dir.rstrip("/"))
            if config_name in ("result.json", "job.log", "config.json"):
                continue

            for ts_dir in glob.glob(f"{config_dir}/*/"):
                for trial_dir in glob.glob(f"{ts_dir}/*__*/"):
                    agent_dir = os.path.join(trial_dir, "agent")
                    traj_path = os.path.join(agent_dir, "trajectory.json")
                    sessions_projects = os.path.join(
                        agent_dir, "sessions", "projects"
                    )

                    # Skip if trajectory already exists
                    if os.path.exists(traj_path):
                        continue

                    # Skip if no sessions directory
                    if not os.path.exists(sessions_projects):
                        continue

                    jsonl_files = glob.glob(
                        f"{sessions_projects}/**/*.jsonl", recursive=True
                    )
                    if not jsonl_files:
                        continue

                    parent_dirs = set(os.path.dirname(f) for f in jsonl_files)

                    # H3 pattern: multiple dirs, with subagents
                    top_level = [
                        d for d in parent_dirs if "subagents" not in d
                    ]
                    subagent_dirs = [
                        d for d in parent_dirs if "subagents" in d
                    ]

                    if len(parent_dirs) > 1 and len(top_level) == 1:
                        # This is an H3 case
                        main_jsonl = [
                            f
                            for f in jsonl_files
                            if os.path.dirname(f) == top_level[0]
                        ]
                        subagent_jsonl = [
                            f
                            for f in jsonl_files
                            if "subagents" in f
                        ]

                        task_name = os.path.basename(trial_dir.rstrip("/"))
                        affected.append(
                            {
                                "trial_dir": trial_dir,
                                "agent_dir": agent_dir,
                                "traj_path": traj_path,
                                "session_dir": top_level[0],
                                "main_jsonl": main_jsonl,
                                "subagent_jsonl": subagent_jsonl,
                                "config": config_name,
                                "task": task_name,
                                "batch": batch_name,
                            }
                        )

                        if verbose:
                            print(
                                f"  H3: {config_name}/{task_name} "
                                f"({len(main_jsonl)} main, "
                                f"{len(subagent_jsonl)} subagent files)"
                            )

    return affected


def generate_trajectory(session_dir: str) -> dict | None:
    """Generate trajectory using Harbor's ClaudeCode class.

    Returns the trajectory dict if successful, None otherwise.
    """
    try:
        from harbor.agents.installed.claude_code import ClaudeCode

        # Create a temporary agent instance just for conversion
        agent = ClaudeCode.__new__(ClaudeCode)
        agent.model_name = None

        trajectory = agent._convert_events_to_trajectory(Path(session_dir))
        if trajectory:
            return trajectory.to_json_dict()
    except ImportError:
        print("ERROR: Cannot import harbor.agents.installed.claude_code")
        print("Make sure the harbor package is installed in this environment.")
        sys.exit(1)
    except Exception as exc:
        print(f"  ERROR converting: {exc}")

    return None


def main():
    parser = argparse.ArgumentParser(
        description="Repair missing trajectory.json files caused by the H3 bug"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write trajectory.json files (default: dry run)",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose output"
    )
    parser.add_argument(
        "--base-dir",
        default=None,
        help="Base directory for runs (default: auto-detect)",
    )
    args = parser.parse_args()

    # Auto-detect base directory
    if args.base_dir:
        base_dir = args.base_dir
    else:
        base_dir = os.path.realpath(
            os.path.join(
                os.path.dirname(__file__),
                "..",
                "runs",
                "official",
            )
        )

    if not os.path.exists(base_dir):
        print(f"ERROR: Base directory not found: {base_dir}")
        sys.exit(1)

    print(f"Scanning: {base_dir}")
    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print()

    affected = find_h3_tasks(base_dir, verbose=args.verbose)
    print(f"Found {len(affected)} tasks affected by H3 bug")
    print()

    if not affected:
        print("Nothing to do.")
        return

    # Summary by config
    from collections import Counter

    by_config = Counter(t["config"] for t in affected)
    for config, count in sorted(by_config.items()):
        print(f"  {config}: {count}")
    print()

    if not args.apply:
        print("Run with --apply to generate trajectory.json files.")
        return

    # Generate trajectories
    success = 0
    failed = 0

    for task in affected:
        if args.verbose:
            print(f"Processing: {task['config']}/{task['task']}")

        traj_dict = generate_trajectory(task["session_dir"])
        if traj_dict:
            try:
                with open(task["traj_path"], "w") as f:
                    json.dump(traj_dict, f, indent=2)
                success += 1
                if args.verbose:
                    print(f"  Wrote: {task['traj_path']}")
            except OSError as exc:
                failed += 1
                print(f"  ERROR writing {task['traj_path']}: {exc}")
        else:
            failed += 1
            print(f"  FAILED: {task['config']}/{task['task']}")

    print()
    print(f"Results: {success} generated, {failed} failed, {len(affected)} total")

    if success > 0:
        print()
        print("Next steps:")
        print("  1. Regenerate MANIFEST: python3 scripts/generate_manifest.py")
        print("  2. Verify: grep has_trajectory runs/official/MANIFEST.json | grep false | wc -l")


if __name__ == "__main__":
    main()
