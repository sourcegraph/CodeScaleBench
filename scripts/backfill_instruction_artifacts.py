#!/usr/bin/env python3
"""Backfill instruction.txt artifacts into existing trial result directories.

For each trial-level result.json, this script:
1. Reads the original instruction.md from the task directory
2. Determines the MCP mode from the directory path (baseline, sourcegraph_full, etc.)
3. For hybrid MCP modes, reconstructs the MCP preamble that would have been prepended
4. Writes instruction.txt into the trial directory

This matches what the agent code now does prospectively in create_run_agent_commands().

Usage:
    python3 scripts/backfill_instruction_artifacts.py [--dry-run]
"""

import json
import os
import re
import sys
from pathlib import Path


# Known MCP modes that get the preamble
HYBRID_MCP_MODES = {"sourcegraph_full", "sourcegraph_base"}

# All 3config scripts' TASK_SG_REPO_NAMES mappings (hardcoded here for backfill)
# These match the associative arrays in the config scripts.
TASK_SG_REPO_NAMES = {
    # crossrepo
    "api_upgrade_01": "sg-benchmarks/etcd--d89978e8",
    "bug_localization_01": "sg-benchmarks/scikit-learn--cb7e82dd",
    "cross_file_reasoning_01": "sg-benchmarks/kubernetes--8c9c67c0",
    "refactor_rename_01": "sg-benchmarks/django--674eda1c",
    "simple_test_01": "sg-benchmarks/kubernetes--8c9c67c0",
    # k8s_docs (all tasks share one repo)
    "k8sdocs-001": "sg-benchmarks/kubernetes--8c9c67c0",
    "k8sdocs-002": "sg-benchmarks/kubernetes--8c9c67c0",
    "k8sdocs-003": "sg-benchmarks/kubernetes--8c9c67c0",
    "k8sdocs-004": "sg-benchmarks/kubernetes--8c9c67c0",
    "k8sdocs-005": "sg-benchmarks/kubernetes--8c9c67c0",
}


def detect_mcp_mode(trial_dir: str) -> str:
    """Detect MCP mode from directory path.

    Directory structure: .../runs/.../run_name/MODE/timestamp/trial_id/
    MODE is one of: baseline, sourcegraph_full, sourcegraph_base
    """
    parts = Path(trial_dir).parts
    for mode in ("sourcegraph_full", "sourcegraph_base", "baseline",
                 "sourcegraph", "deepsearch", "deepsearch_hybrid"):
        if mode in parts:
            return mode
    # Validation runs without explicit mode dir are baseline
    return "none"


def resolve_repo_display(task_path: str, task_name: str) -> str:
    """Resolve the Sourcegraph repo display name for a task.

    Mirrors _get_repo_display() logic but uses task metadata instead of env vars.
    """
    # Check hardcoded mappings first
    if task_name in TASK_SG_REPO_NAMES:
        return TASK_SG_REPO_NAMES[task_name]

    # Locobench: read LOCOBENCH_PROJECT_ID from docker-compose.yaml
    dc_file = os.path.join(task_path, "environment", "docker-compose.yaml")
    if os.path.exists(dc_file):
        with open(dc_file) as f:
            for line in f:
                if "LOCOBENCH_PROJECT_ID=" in line:
                    proj_id = line.strip().split("LOCOBENCH_PROJECT_ID=")[-1]
                    if proj_id:
                        return f"sg-benchmarks/locobench-{proj_id}"

    # SWE-bench Pro: parse task_id for org/repo/commit
    m = re.match(r"(?:instance_)?(.+?)__(.+?)-([a-f0-9]{7,40})", task_name)
    if m:
        org = m.group(1).replace("__", "/")
        repo = m.group(2)
        commit = m.group(3)[:8]
        return f"sg-benchmarks/{org}--{repo}--{commit}"

    # Check other 3config script mappings by reading them dynamically
    # (dependeval, dibench, largerepo, pytorch, repoqa, sweperf, tac)
    configs_dir = Path(__file__).parent.parent / "configs"
    for config_file in configs_dir.glob("*_3config.sh"):
        repo_name = _extract_repo_from_config(config_file, task_name)
        if repo_name:
            return repo_name

    return "the codebase"


def _extract_repo_from_config(config_file: Path, task_name: str) -> str:
    """Extract SOURCEGRAPH_REPO_NAME for a task from a 3config.sh script."""
    try:
        content = config_file.read_text()
        # Look for patterns like: ["task_name"]="sg-benchmarks/repo--commit"
        pattern = rf'\["{re.escape(task_name)}"\]="([^"]+)"'
        m = re.search(pattern, content)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def build_mcp_preamble(mcp_mode: str, repo_display: str) -> str:
    """Reconstruct the MCP preamble that would have been prepended.

    Mirrors the logic in create_run_agent_commands().
    """
    if mcp_mode not in HYBRID_MCP_MODES:
        return ""

    deepsearch_line = ""
    if mcp_mode == "sourcegraph_full":
        deepsearch_line = "\n- For complex code understanding questions, use `mcp__sourcegraph__sg_deepsearch`"

    if repo_display != "the codebase":
        repo_line = f"Repository filter for sg_keyword_search: `repo:^github.com/{repo_display}$ QUERY`"
    else:
        repo_line = "Run `mcp__sourcegraph__sg_list_repos` first to find available repos."

    return f"""## MANDATORY: Use Sourcegraph MCP for Code Search

You have Sourcegraph MCP tools. You MUST use them INSTEAD OF Grep, Glob, and bash grep/rg/find for ALL code search.

- Instead of Grep -> use `mcp__sourcegraph__sg_keyword_search`
- Instead of Glob -> use `mcp__sourcegraph__sg_list_files`
- For symbol definitions -> use `mcp__sourcegraph__sg_go_to_definition`
- For all references -> use `mcp__sourcegraph__sg_find_references`{deepsearch_line}

{repo_line}

If you catch yourself reaching for Grep or Glob to *find* code, STOP and use Sourcegraph instead.
The only acceptable use of Grep/Glob is verifying content in a file you already located via Sourcegraph.

---

"""


def find_instruction(task_path: str, trial_dir: str) -> str:
    """Find and read the original instruction for a task.

    Resolution order:
    1. instruction.md in the task directory (local benchmarks)
    2. First user message in agent/trajectory.json (Harbor-managed datasets like swebenchpro)
    """
    # Try local instruction file first
    for candidate in [
        os.path.join(task_path, "instruction.md"),
        os.path.join(task_path, "instruction.txt"),
    ]:
        if os.path.exists(candidate):
            with open(candidate) as f:
                return f.read()

    # Fall back to trajectory.json: the first user step contains the instruction
    trajectory_path = os.path.join(trial_dir, "agent", "trajectory.json")
    if os.path.exists(trajectory_path):
        try:
            with open(trajectory_path) as f:
                traj = json.load(f)
            for step in traj.get("steps", []):
                if step.get("source") == "user" and step.get("message"):
                    return step["message"]
        except Exception:
            pass

    return ""


def main():
    dry_run = "--dry-run" in sys.argv

    search_roots = [
        Path("/home/stephanie_jarmak/evals/custom_agents/agents/claudecode/runs/official"),
        Path("/home/stephanie_jarmak/CodeContextBench/runs/validation"),
    ]

    trial_count = 0
    written_count = 0
    skipped_count = 0
    error_count = 0

    for root in search_roots:
        if not root.exists():
            print(f"Skipping {root} (not found)")
            continue

        for dirpath, dirnames, filenames in os.walk(root):
            if "result.json" not in filenames:
                continue

            result_path = os.path.join(dirpath, "result.json")
            try:
                with open(result_path) as f:
                    result = json.load(f)
            except Exception as e:
                print(f"  ERROR reading {result_path}: {e}")
                error_count += 1
                continue

            task_name = result.get("task_name", "")
            task_path = result.get("task_id", {}).get("path", "")

            # Skip aggregate-level result.json (no task_name)
            if not task_name or not task_path:
                continue

            trial_count += 1
            instruction_out = os.path.join(dirpath, "instruction.txt")

            # Skip if already exists
            if os.path.exists(instruction_out):
                skipped_count += 1
                continue

            # Read original instruction (from task dir or trajectory fallback)
            instruction = find_instruction(task_path, dirpath)
            if not instruction:
                print(f"  WARNING: No instruction found for {task_name} (task_path={task_path}, trial_dir={dirpath})")
                error_count += 1
                continue

            # Determine MCP mode and reconstruct preamble
            mcp_mode = detect_mcp_mode(dirpath)
            repo_display = resolve_repo_display(task_path, task_name)
            preamble = build_mcp_preamble(mcp_mode, repo_display)

            final_instruction = preamble + instruction

            if dry_run:
                has_preamble = "YES" if preamble else "no"
                print(f"  [DRY-RUN] {dirpath}")
                print(f"    task={task_name}  mode={mcp_mode}  repo={repo_display}  preamble={has_preamble}  len={len(final_instruction)}")
            else:
                with open(instruction_out, "w") as f:
                    f.write(final_instruction)
                written_count += 1

    print()
    print(f"Trials found:  {trial_count}")
    print(f"Written:       {written_count}")
    print(f"Skipped (exist): {skipped_count}")
    print(f"Errors:        {error_count}")


if __name__ == "__main__":
    main()
