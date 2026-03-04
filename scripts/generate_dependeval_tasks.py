#!/usr/bin/env python3
"""Generate Harbor-compatible task directories for DependEval instances.

Reads selected instances from configs/dependeval_selected_instances.json,
fetches source data from vendor/DependEval/data/, and generates complete
Harbor task directories under benchmarks/archive/ccb_dependeval/.

Each task directory contains:
  - task.toml          (Harbor task metadata)
  - instruction.md     (agent instructions, baseline-clean)
  - environment/Dockerfile
  - environment/code_content.txt
  - tests/test.sh
  - tests/ground_truth.json
  - tests/eval_scripts/eval_{dr,me}.py
  - solution/solve.sh
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SELECTION = Path("configs/dependeval_selected_instances.json")
DEFAULT_DATA_DIR = Path("vendor/DependEval/data")
DEFAULT_OUTPUT_DIR = Path("benchmarks/archive/ccb_dependeval")
DEFAULT_EVAL_DR = Path("scripts/dependeval_eval_dr.py")
DEFAULT_EVAL_ME = Path("scripts/dependeval_eval_me.py")

ME_FILE_PATTERN = "task1_{lang}.json"
DR_FILE_PATTERN = "task2_{lang}_final.json"

# Regex to match file header lines: 'repo_name/path/to/file.ext'
FILE_HEADER_RE = re.compile(r"^'([^']+/[^']+)'$")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def instance_id_from_content(content: str) -> str:
    """Return first 8 hex chars of SHA-256 of the content string."""
    return hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:8]


def find_instance_in_data(
    data_dir: Path, language: str, task_type: str, target_id: str
) -> dict | None:
    """Find the instance with matching instance_id in the data file."""
    if task_type == "ME":
        filepath = data_dir / language / ME_FILE_PATTERN.format(lang=language)
    else:
        filepath = data_dir / language / DR_FILE_PATTERN.format(lang=language)

    if not filepath.exists():
        print(f"  WARNING: Data file not found: {filepath}", file=sys.stderr)
        return None

    with open(filepath) as f:
        raw = json.load(f)

    for inst in raw:
        content = inst.get("content", "")
        iid = instance_id_from_content(content)
        if iid == target_id:
            return inst

    return None


# ---------------------------------------------------------------------------
# Task name helpers
# ---------------------------------------------------------------------------

def make_task_name(task_type: str, language: str, instance_id: str) -> str:
    """Build task directory name: {task_type_full}-{language}-{instance_id}."""
    if task_type == "DR":
        return f"dependency_recognition-{language}-{instance_id}"
    else:
        return f"multifile_editing-{language}-{instance_id}"


# ---------------------------------------------------------------------------
# File generators
# ---------------------------------------------------------------------------

def generate_task_toml(
    task_name: str, task_type: str, language: str, instance_id: str,
    repo_name: str, difficulty: str = "medium",
) -> str:
    """Generate task.toml content."""
    tt_full = "dependency_recognition" if task_type == "DR" else "multifile_editing"
    return f"""version = "1.0"

[task]
name = "{task_name}"
description = "DependEval {tt_full} task for {language} ({repo_name})"
task_type = "{tt_full}"
language = "{language}"
difficulty = "{difficulty}"
time_limit_sec = 600

[metadata]
source = "DependEval"
repo_name = "{repo_name}"
instance_id = "{instance_id}"

[evaluation]
output_file = "submission.json"
reward_file = "/logs/verifier/reward.txt"

[environment]
build_timeout_sec = 300.0

[environment.setup_scripts]
mcp_config = \"\"\"#!/bin/bash
# Setup Sourcegraph MCP if credentials provided
if [ -n "$SOURCEGRAPH_ACCESS_TOKEN" ] && [ -n "$SOURCEGRAPH_URL" ]; then
  mkdir -p /root/.config/claude
  cat > /root/.config/claude/mcp.json << 'MCPEOF'
{{
  "mcpServers": {{
    "sourcegraph": {{
      "command": "npx",
      "args": ["-y", "@sourcegraph/mcp-server"],
      "env": {{
        "SRC_ACCESS_TOKEN": "$SOURCEGRAPH_ACCESS_TOKEN",
        "SOURCEGRAPH_URL": "$SOURCEGRAPH_URL"
      }}
    }}
  }}
}}
MCPEOF
  echo "PASS MCP configuration created"
else
  echo "No Sourcegraph credentials provided, MCP disabled"
fi
exit 0
\"\"\"
"""


def generate_dr_instruction(
    repo_name: str, language: str, instance_id: str,
    content: str, files: list[str],
) -> str:
    """Generate instruction.md for a DR (Dependency Recognition / file ordering) task."""
    # Build the file list for display
    file_list_display = "\n".join(f"- `{f.strip().strip(chr(39))}`" for f in files)
    ext = _lang_ext(language)

    return f"""# File Dependency Ordering Task

**Repository:** {repo_name}
**Language:** {language}
**Difficulty:** MEDIUM
**Task Type:** Dependency Recognition (File Ordering)

## Description

You are given source code from the **{repo_name}** repository. Your task is to determine the correct dependency ordering of the files listed below. Files that are depended upon (callees) should come before files that depend on them (callers).

## Files to Order

The following files need to be arranged in dependency order (dependencies first):

{file_list_display}

## Source Code

The source code is available in `/workspace/code_content.txt`. Read it carefully to understand the import/dependency relationships between files.

## Task

1. Read the source code from `/workspace/code_content.txt`
2. Analyze the import statements and dependency relationships between files
3. Determine the correct ordering where each file appears after all files it depends on
4. Write the ordered list to `/workspace/submission.json`

## Output Format

Write your answer to `/workspace/submission.json` as a JSON array of file paths in dependency order (dependencies first, dependents last):

```json
[
  "'repo_name/path/to/base_file.{ext}'",
  "'repo_name/path/to/dependent_file.{ext}'"
]
```

**Important:** Use the exact file path strings as listed above, including the surrounding single quotes.

## Evaluation

Your submission is scored by element-wise exact match averaged across positions. Each position where your file matches the correct ordering scores 1/N, where N is the total number of files.

**Time Limit:** 10 minutes
"""


def generate_me_instruction(
    repo_name: str, language: str, instance_id: str,
    content: str, feature_description: str, detailed_description: str,
    file_count: int,
) -> str:
    """Generate instruction.md for an ME (Multi-file Editing) task."""
    # Use detailed description if available, fall back to short
    description = detailed_description.strip() if detailed_description.strip() else feature_description.strip()

    return f"""# Multi-File Code Editing Task

**Repository:** {repo_name}
**Language:** {language}
**Difficulty:** MEDIUM
**Task Type:** Multi-file Editing

## Description

You are given source code from the **{repo_name}** repository. Your task is to implement a feature modification that requires changes across multiple files.

## Feature to Implement

{description}

## Source Code

The source code is available in `/workspace/code_content.txt`. Read it carefully to understand the current implementation before making changes.

## Task

1. Read the source code from `/workspace/code_content.txt`
2. Understand the current code structure and the feature request above
3. Implement the required changes across the relevant files
4. Write your modified files to `/workspace/submission.json`

## Output Format

Write your answer to `/workspace/submission.json` as a JSON object mapping file paths to their complete modified source code:

```json
{{
  "path/to/file1.{_lang_ext(language)}": "complete modified source code for file1...",
  "path/to/file2.{_lang_ext(language)}": "complete modified source code for file2..."
}}
```

**Important:**
- Include the **complete** modified source code for each file, not just the changes
- Use relative file paths (without the repository name prefix)
- Include all {file_count} files that need modifications

## Evaluation

Your submission is scored by average string similarity (per-file) between your modified code and the expected modifications. Higher similarity to the expected output yields a higher score.

**Time Limit:** 10 minutes
"""


def _lang_ext(language: str) -> str:
    """Return typical file extension for a language."""
    return {
        "python": "py",
        "java": "java",
        "javascript": "js",
        "typescript": "ts",
    }.get(language, "txt")


def generate_dockerfile(language: str) -> str:
    """Generate Dockerfile for the task environment."""
    return """FROM python:3.10.13-slim

WORKDIR /workspace

# Install system dependencies
RUN apt-get update && apt-get install -y \\
    git \\
    curl \\
    && rm -rf /var/lib/apt/lists/*

# Install Node.js for Claude Code CLI
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \\
    apt-get install -y nodejs && \\
    rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# Copy code content for agent analysis
COPY code_content.txt /workspace/code_content.txt

# Set up output directories
RUN mkdir -p /logs/verifier /workspace

CMD ["/bin/bash"]
"""


def generate_test_sh(task_type: str) -> str:
    """Generate test.sh that calls the appropriate eval script."""
    eval_script = "eval_dr.py" if task_type == "DR" else "eval_me.py"
    return f"""#!/bin/bash
set -e

# DependEval {task_type} Test Script
# Runs the evaluation script and writes reward to /logs/verifier/reward.txt

mkdir -p /logs/verifier

# Run evaluation
python3 /tests/eval_scripts/{eval_script}

# Ensure we always exit 0 (Harbor requirement)
exit 0
"""


def generate_dr_ground_truth(gt: list[str]) -> str:
    """Generate ground_truth.json for a DR task."""
    return json.dumps(gt, indent=2) + "\n"


def generate_me_ground_truth(modified_complete_code: dict) -> str:
    """Generate ground_truth.json for an ME task."""
    return json.dumps(modified_complete_code, indent=2) + "\n"


def generate_solve_sh(task_type: str) -> str:
    """Generate solution/solve.sh that copies ground truth to submission."""
    return """#!/bin/bash
set -e

# Oracle solution — copies ground truth to submission
cp /tests/ground_truth.json /workspace/submission.json

exit 0
"""


# ---------------------------------------------------------------------------
# Task directory builder
# ---------------------------------------------------------------------------

def generate_task_directory(
    output_dir: Path,
    task_name: str,
    task_type: str,
    language: str,
    instance_id: str,
    repo_name: str,
    instance_data: dict,
    eval_dr_path: Path,
    eval_me_path: Path,
    dry_run: bool = False,
) -> bool:
    """Generate a complete Harbor task directory. Returns True on success."""
    task_dir = output_dir / task_name

    if dry_run:
        print(f"  [DRY RUN] Would create: {task_dir}")
        return True

    # Remove existing task dir if present (for idempotent regeneration)
    if task_dir.exists():
        shutil.rmtree(task_dir)

    # Create directory structure
    (task_dir / "environment").mkdir(parents=True)
    (task_dir / "tests" / "eval_scripts").mkdir(parents=True)
    (task_dir / "solution").mkdir(parents=True)

    content = instance_data.get("content", "")

    # 1. task.toml
    toml_content = generate_task_toml(
        task_name, task_type, language, instance_id, repo_name
    )
    (task_dir / "task.toml").write_text(toml_content)

    # 2. instruction.md
    if task_type == "DR":
        files = instance_data.get("files", [])
        instruction = generate_dr_instruction(
            repo_name, language, instance_id, content, files
        )
    else:
        feature_desc = instance_data.get("feature_description", "")
        detailed_desc = instance_data.get("detailed_feature_description", "")
        # Count files from content
        file_count = sum(1 for line in content.splitlines()
                        if FILE_HEADER_RE.match(line.strip()))
        instruction = generate_me_instruction(
            repo_name, language, instance_id, content,
            feature_desc, detailed_desc, file_count
        )
    (task_dir / "instruction.md").write_text(instruction)

    # 3. environment/Dockerfile
    dockerfile = generate_dockerfile(language)
    (task_dir / "environment" / "Dockerfile").write_text(dockerfile)

    # 4. environment/code_content.txt (raw content from DependEval)
    (task_dir / "environment" / "code_content.txt").write_text(content)

    # 5. tests/test.sh
    test_sh = generate_test_sh(task_type)
    test_sh_path = task_dir / "tests" / "test.sh"
    test_sh_path.write_text(test_sh)
    test_sh_path.chmod(test_sh_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    # 6. tests/ground_truth.json
    if task_type == "DR":
        gt = instance_data.get("gt", [])
        gt_content = generate_dr_ground_truth(gt)
    else:
        mcc = instance_data.get("modified_complete_code", {})
        gt_content = generate_me_ground_truth(mcc)
    (task_dir / "tests" / "ground_truth.json").write_text(gt_content)

    # 7. tests/eval_scripts/eval_{dr,me}.py — copy from scripts/
    if task_type == "DR":
        shutil.copy2(eval_dr_path, task_dir / "tests" / "eval_scripts" / "eval_dr.py")
    else:
        shutil.copy2(eval_me_path, task_dir / "tests" / "eval_scripts" / "eval_me.py")

    # 8. solution/solve.sh
    solve_sh = generate_solve_sh(task_type)
    solve_sh_path = task_dir / "solution" / "solve.sh"
    solve_sh_path.write_text(solve_sh)
    solve_sh_path.chmod(solve_sh_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate Harbor-compatible task directories for DependEval instances.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  %(prog)s                    # Generate all task directories
  %(prog)s --dry-run          # Show what would be created
  %(prog)s --output-dir /tmp  # Custom output directory
""",
    )
    parser.add_argument(
        "--selection",
        type=Path,
        default=DEFAULT_SELECTION,
        help=f"Path to selected instances JSON (default: {DEFAULT_SELECTION})",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Path to DependEval data directory (default: {DEFAULT_DATA_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory for task dirs (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--eval-dr",
        type=Path,
        default=DEFAULT_EVAL_DR,
        help=f"Path to DR eval script (default: {DEFAULT_EVAL_DR})",
    )
    parser.add_argument(
        "--eval-me",
        type=Path,
        default=DEFAULT_EVAL_ME,
        help=f"Path to ME eval script (default: {DEFAULT_EVAL_ME})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be created without writing to disk",
    )
    args = parser.parse_args()

    # Validate inputs
    if not args.selection.exists():
        print(f"ERROR: Selection file not found: {args.selection}", file=sys.stderr)
        sys.exit(1)

    if not args.data_dir.exists():
        print(f"ERROR: Data directory not found: {args.data_dir}", file=sys.stderr)
        sys.exit(1)

    if not args.eval_dr.exists():
        print(f"ERROR: DR eval script not found: {args.eval_dr}", file=sys.stderr)
        sys.exit(1)

    if not args.eval_me.exists():
        print(f"ERROR: ME eval script not found: {args.eval_me}", file=sys.stderr)
        sys.exit(1)

    # Load selected instances
    with open(args.selection) as f:
        selected = json.load(f)

    print("DependEval Task Directory Generator")
    print(f"  Selection: {args.selection} ({len(selected)} instances)")
    print(f"  Data dir:  {args.data_dir}")
    print(f"  Output:    {args.output_dir}")
    print(f"  Dry run:   {args.dry_run}")
    print("=" * 70)

    if not args.dry_run:
        args.output_dir.mkdir(parents=True, exist_ok=True)

    success_count = 0
    fail_count = 0

    for iid, meta in sorted(selected.items()):
        lang = meta["language"]
        task_type = meta["task_type"]
        repo_name = meta["repo_name"]
        task_name = make_task_name(task_type, lang, iid)

        print(f"\n[{iid}] {lang}/{task_type} ({repo_name}) -> {task_name}")

        # Find instance in source data
        inst = find_instance_in_data(args.data_dir, lang, task_type, iid)
        if inst is None:
            print(f"  ERROR: Instance {iid} not found in {lang}/{task_type} data",
                  file=sys.stderr)
            fail_count += 1
            continue

        ok = generate_task_directory(
            output_dir=args.output_dir,
            task_name=task_name,
            task_type=task_type,
            language=lang,
            instance_id=iid,
            repo_name=repo_name,
            instance_data=inst,
            eval_dr_path=args.eval_dr,
            eval_me_path=args.eval_me,
            dry_run=args.dry_run,
        )

        if ok:
            success_count += 1
            if not args.dry_run:
                print(f"  OK: {task_name}")
        else:
            fail_count += 1

    print(f"\n{'=' * 70}")
    print(f"Results: {success_count} generated, {fail_count} failed")

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
