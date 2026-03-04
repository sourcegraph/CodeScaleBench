#!/usr/bin/env python3
"""Generate Dockerfile.artifact_only for all tasks that are missing one.

For each task with a Dockerfile but no Dockerfile.artifact_only:
  - Reads the original Dockerfile
  - Checks Dockerfile.sg_only for /repo_full to classify as build-requiring vs write-only
  - Detects the workspace path from sg_only (e.g., /app for SWE-bench Pro, /workspace otherwise)
  - Generates Dockerfile.artifact_only:
      Build-requiring: original + /repo_full backup + sentinel
      Write-only: original + sentinel only

Usage:
    python3 scripts/generate_artifact_dockerfiles.py [--dry-run] [--suite SUITE]
"""

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS = ROOT / "benchmarks"


def find_tasks(suite_filter: str | None = None) -> list[Path]:
    """Find tasks missing Dockerfile.artifact_only."""
    pattern = f"ccb_{suite_filter}" if suite_filter else "ccb_*"
    tasks = []
    for task_dir in sorted(BENCHMARKS.glob(f"{pattern}/*/environment")):
        if not task_dir.is_dir():
            continue
        dockerfile = task_dir / "Dockerfile"
        artifact = task_dir / "Dockerfile.artifact_only"
        if dockerfile.exists() and not artifact.exists():
            tasks.append(task_dir.parent)
    return tasks


def is_build_requiring(task_dir: Path) -> bool:
    """Check if task's Dockerfile.sg_only uses /repo_full (build-requiring)."""
    sg_only = task_dir / "environment" / "Dockerfile.sg_only"
    if not sg_only.exists():
        return False
    return "repo_full" in sg_only.read_text()


def get_workdir_from_sgonly(task_dir: Path) -> str:
    """Extract the workspace path from sg_only's .sg_only_workdir sentinel.

    SWE-bench Pro tasks use /app, most others use /workspace.
    Falls back to /workspace if no sentinel found.
    """
    sg_only = task_dir / "environment" / "Dockerfile.sg_only"
    if not sg_only.exists():
        return "/workspace"
    text = sg_only.read_text()
    # Match: echo '/app' > /tmp/.sg_only_workdir
    m = re.search(r"echo\s+'(/[^']+)'\s*>\s*/tmp/\.sg_only_workdir", text)
    if m:
        return m.group(1)
    return "/workspace"


def has_defect_injection(task_dir: Path) -> bool:
    """Check if task has inject_defects.sh."""
    return (task_dir / "environment" / "inject_defects.sh").exists()


def generate_artifact_dockerfile(task_dir: Path) -> str:
    """Generate Dockerfile.artifact_only content for a task."""
    task_name = task_dir.name
    original = (task_dir / "environment" / "Dockerfile").read_text()
    build_req = is_build_requiring(task_dir)
    workdir = get_workdir_from_sgonly(task_dir)

    # Header comment
    mode_desc = "build-requiring" if build_req else "write-only"
    header = f"# {task_name} — artifact_only variant ({mode_desc})\n"
    header += "# Repos cloned for baseline agent to read locally.\n"
    header += "# MCP agent deletes source files at runtime via agent startup script.\n"
    if build_req:
        header += "# Verifier applies patches from review.json to /repo_full copy for scoring.\n"
    else:
        header += "# Verifier scores agent output only — no repo restore needed.\n"

    # Split original at last ENTRYPOINT or CMD line
    lines = original.rstrip().split("\n")
    terminal_idx = None
    terminal_keyword = None
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped.startswith("ENTRYPOINT"):
            terminal_idx = i
            terminal_keyword = "ENTRYPOINT"
            break
        if stripped.startswith("CMD"):
            terminal_idx = i
            terminal_keyword = "CMD"
            break

    if terminal_idx is None:
        pre_terminal = lines
        terminal_line = "ENTRYPOINT []"
    else:
        pre_terminal = lines[:terminal_idx]
        # Always use ENTRYPOINT [] for artifact_only (consistent with other variants)
        terminal_line = "ENTRYPOINT []"

    # Build artifact_only block
    artifact_block = []
    artifact_block.append("")

    if build_req:
        artifact_block.append("# --- artifact_only: backup full repo for verifier scoring ---")
        artifact_block.append(f"# Source stays in {workdir} (readable by baseline agent).")
        artifact_block.append("# MCP agent deletes source files at runtime via agent startup script.")
        artifact_block.append(f"RUN cp -a {workdir} /repo_full")
        artifact_block.append(f"RUN touch /tmp/.artifact_only_mode && echo '{workdir}' > /tmp/.artifact_only_workdir")
    else:
        artifact_block.append("# --- artifact_only mode ---")
        artifact_block.append("# Sentinel flag for artifact-based verification.")
        artifact_block.append("# Source stays readable for baseline agent; MCP agent deletes at runtime.")
        artifact_block.append("RUN touch /tmp/.artifact_only_mode")

    artifact_block.append("")
    artifact_block.append(terminal_line)
    artifact_block.append("")

    # Combine: header + original (minus terminal) + artifact block
    result = header + "\n" + "\n".join(pre_terminal) + "\n".join(artifact_block)
    return result


def main():
    parser = argparse.ArgumentParser(description="Generate Dockerfile.artifact_only files")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be generated")
    parser.add_argument("--suite", type=str, help="Only process this suite (e.g., build, fix)")
    args = parser.parse_args()

    tasks = find_tasks(args.suite)

    if not tasks:
        print("All tasks already have Dockerfile.artifact_only!")
        return

    build_req_count = 0
    write_only_count = 0

    for task_dir in tasks:
        task_name = task_dir.name
        suite = task_dir.parent.name
        build_req = is_build_requiring(task_dir)
        workdir = get_workdir_from_sgonly(task_dir)
        mode = f"build-requiring ({workdir})" if build_req else "write-only"

        if build_req:
            build_req_count += 1
        else:
            write_only_count += 1

        output_path = task_dir / "environment" / "Dockerfile.artifact_only"

        if args.dry_run:
            print(f"  {suite}/{task_name}: {mode}")
            continue

        content = generate_artifact_dockerfile(task_dir)
        output_path.write_text(content)
        print(f"  {suite}/{task_name}: {mode} -> {output_path.name}")

    print(f"\n{'Would generate' if args.dry_run else 'Generated'}: "
          f"{len(tasks)} files ({build_req_count} build-requiring, {write_only_count} write-only)")


if __name__ == "__main__":
    main()
