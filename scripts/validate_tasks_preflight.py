#!/usr/bin/env python3
"""Pre-flight validation of benchmark tasks before launching runs.

Checks task definitions for known problems that would waste compute:
- Truncated instruction.md
- task.toml language/difficulty mismatches vs selected_benchmark_tasks.json
- test.sh missing or not executable
- Missing task in selection registry
- Crossrepo expected_changes content mismatches

Usage:
    # Validate all tasks in a suite
    python3 scripts/validate_tasks_preflight.py --suite ccb_pytorch

    # Validate all selected tasks
    python3 scripts/validate_tasks_preflight.py --all

    # Validate a single task
    python3 scripts/validate_tasks_preflight.py --task benchmarks/ccb_pytorch/sgt-005

    # JSON output
    python3 scripts/validate_tasks_preflight.py --all --format json

    # Runtime smoke (no agent): Docker build + verifier execution
    python3 scripts/validate_tasks_preflight.py --task benchmarks/ccb_largerepo/big-code-k8s-001 --smoke-runtime

    # Runtime smoke for a full suite (expensive)
    python3 scripts/validate_tasks_preflight.py --suite ccb_largerepo --smoke-runtime --smoke-timeout-sec 900
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS_DIR = PROJECT_ROOT / "benchmarks"
SELECTED_TASKS_PATH = PROJECT_ROOT / "configs" / "selected_benchmark_tasks.json"

# Minimum instruction.md length (characters) to consider non-truncated
MIN_INSTRUCTION_LENGTH = 200

# Template placeholder patterns that should have been replaced
TEMPLATE_PATTERNS = [
    re.compile(r"#ISSUE_NUMBER"),
    re.compile(r"#REPO_NAME"),
    re.compile(r"\{\{.*?\}\}"),
    re.compile(r"<PLACEHOLDER>"),
    re.compile(r"TODO:?\s*fill"),
]


def load_selected_tasks() -> dict:
    """Load selected_benchmark_tasks.json and index by (benchmark, task_id)."""
    if not SELECTED_TASKS_PATH.is_file():
        return {}
    data = json.loads(SELECTED_TASKS_PATH.read_text())
    index = {}
    for task in data.get("tasks", []):
        key = (task.get("benchmark", ""), task.get("task_id", ""))
        index[key] = task
    return index


def parse_task_toml_simple(path: Path) -> dict:
    """Minimal TOML parser for task.toml (avoids tomllib dependency).

    Handles flat key=value and [section] headers. Enough for our fields.
    """
    result = {}
    section = ""
    if not path.is_file():
        return result
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line.strip("[]").strip()
            continue
        if "=" in line:
            # Handle multi-line strings (triple-quoted) — skip them
            if '"""' in line:
                break
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            full_key = f"{section}.{key}" if section else key
            result[full_key] = val
    return result


def validate_task(task_dir: Path, selected_index: dict) -> list[dict]:
    """Validate a single task directory. Returns list of issues."""
    issues = []
    task_name = task_dir.name

    # Determine benchmark from parent dir
    benchmark = task_dir.parent.name
    # Handle tasks/ subdirectory (swebenchpro)
    if benchmark == "tasks":
        benchmark = task_dir.parent.parent.name

    def issue(severity: str, check: str, message: str):
        issues.append({
            "severity": severity,
            "check": check,
            "task": task_name,
            "benchmark": benchmark,
            "message": message,
            "path": str(task_dir),
        })

    # --- Check instruction.md ---
    instruction_path = task_dir / "instruction.md"
    if not instruction_path.is_file():
        issue("CRITICAL", "missing_instruction", "No instruction.md found")
    else:
        content = instruction_path.read_text(errors="replace")
        if len(content) < MIN_INSTRUCTION_LENGTH:
            issue("CRITICAL", "truncated_instruction",
                  f"instruction.md is only {len(content)} chars (minimum: {MIN_INSTRUCTION_LENGTH})")

        # Check for template placeholders
        for pattern in TEMPLATE_PATTERNS:
            match = pattern.search(content)
            if match:
                issue("WARNING", "template_placeholder",
                      f"instruction.md contains template placeholder: {match.group(0)}")

    # --- Check task.toml ---
    toml_path = task_dir / "task.toml"
    if not toml_path.is_file():
        issue("WARNING", "missing_task_toml", "No task.toml found")
        toml_data = {}
    else:
        toml_data = parse_task_toml_simple(toml_path)

    # --- Check test.sh ---
    test_sh = task_dir / "tests" / "test.sh"
    if not test_sh.is_file():
        issue("CRITICAL", "missing_test_sh", "No tests/test.sh found")
    else:
        if not os.access(test_sh, os.X_OK):
            issue("WARNING", "test_not_executable", "tests/test.sh is not executable")

        # Check for known bad patterns in test.sh
        test_content = test_sh.read_text(errors="replace")
        if "--output_path" in test_content and "--result_path" not in test_content:
            # Check if this is a TAC task with the known --output_path bug
            if "tac" in benchmark.lower():
                issue("WARNING", "test_sh_bad_flag",
                      "test.sh uses --output_path (should be --result_path for TAC tasks)")

    # --- Cross-check with selected_benchmark_tasks.json ---
    selected_key = (benchmark, task_name)
    selected = selected_index.get(selected_key)

    if not selected:
        # Also try with the task_dir field
        for key, val in selected_index.items():
            if val.get("task_dir", "").endswith(f"/{task_name}"):
                selected = val
                break

    if selected:
        # Check language match
        toml_language = toml_data.get("task.language", "")
        selected_language = selected.get("language", "")
        if toml_language and selected_language and toml_language != selected_language:
            issue("WARNING", "language_mismatch",
                  f"task.toml language='{toml_language}' vs selected_tasks language='{selected_language}'")

        # Check difficulty match
        toml_difficulty = toml_data.get("task.difficulty", "")
        selected_difficulty = selected.get("difficulty", "")
        if toml_difficulty and selected_difficulty and toml_difficulty != selected_difficulty:
            issue("WARNING", "difficulty_mismatch",
                  f"task.toml difficulty='{toml_difficulty}' vs selected_tasks difficulty='{selected_difficulty}'")
    else:
        issue("INFO", "not_in_selection",
              f"Task not found in selected_benchmark_tasks.json")

    # --- Check expected_changes.json (crossrepo) ---
    expected_changes = task_dir / "expected_changes.json"
    if expected_changes.is_file() and instruction_path.is_file():
        try:
            ec_content = expected_changes.read_text()
            instr_content = instruction_path.read_text(errors="replace")

            # Extract repo references from expected_changes
            ec_data = json.loads(ec_content)
            ec_repos = set()
            if isinstance(ec_data, dict):
                for key in ec_data:
                    # Keys often contain repo/file paths
                    parts = key.split("/")
                    if len(parts) >= 2:
                        ec_repos.add(parts[0].lower())

            # Check if expected_changes references repos not in instruction
            instr_lower = instr_content.lower()
            for repo in ec_repos:
                if repo and len(repo) > 3 and repo not in instr_lower:
                    issue("WARNING", "expected_changes_mismatch",
                          f"expected_changes.json references '{repo}' not found in instruction.md")
        except (json.JSONDecodeError, OSError):
            issue("WARNING", "expected_changes_invalid",
                  "expected_changes.json is not valid JSON")

    return issues


def _shorten(text: str, limit: int = 500) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def smoke_task_runtime(
    task_dir: Path,
    timeout_sec: int = 300,
    build_timeout_sec: int | None = None,
    verify_timeout_sec: int | None = None,
) -> list[dict]:
    """Build task image and run verifier without an agent.

    This catches broken Dockerfiles and verifier script/runtime wiring before
    expensive benchmark batches are launched.
    """
    issues: list[dict] = []
    benchmark = task_dir.parent.name if task_dir.parent.name != "tasks" else task_dir.parent.parent.name
    task_name = task_dir.name

    def issue(severity: str, check: str, message: str):
        issues.append({
            "severity": severity,
            "check": check,
            "task": task_name,
            "benchmark": benchmark,
            "message": message,
            "path": str(task_dir),
        })

    if shutil.which("docker") is None:
        issue("CRITICAL", "smoke_no_docker", "docker not found on PATH")
        return issues

    dockerfile = task_dir / "environment" / "Dockerfile"
    tests_dir = task_dir / "tests"
    test_sh = tests_dir / "test.sh"
    if not dockerfile.is_file():
        issue("CRITICAL", "smoke_missing_dockerfile", "Missing environment/Dockerfile")
        return issues
    if not test_sh.is_file():
        issue("CRITICAL", "smoke_missing_test_sh", "Missing tests/test.sh")
        return issues

    image_tag = f"ccb-smoke-{task_name.lower().replace('_', '-')}-{uuid.uuid4().hex[:8]}"
    build_timeout = build_timeout_sec if build_timeout_sec is not None else timeout_sec
    verify_timeout = verify_timeout_sec if verify_timeout_sec is not None else timeout_sec

    try:
        build_contexts = [task_dir, dockerfile.parent]
        build_succeeded = False
        build_errors: list[str] = []
        saw_build_timeout = False
        for ctx in build_contexts:
            try:
                build = subprocess.run(
                    ["docker", "build", "-f", str(dockerfile), "-t", image_tag, str(ctx)],
                    capture_output=True,
                    text=True,
                    timeout=build_timeout,
                    check=False,
                )
                if build.returncode == 0:
                    build_succeeded = True
                    break
                build_errors.append(f"context={ctx}: {_shorten(build.stdout + chr(10) + build.stderr)}")
            except subprocess.TimeoutExpired:
                saw_build_timeout = True
                build_errors.append(f"context={ctx}: timeout ({build_timeout}s)")

        if not build_succeeded:
            check_name = "smoke_build_timeout" if saw_build_timeout else "smoke_docker_build_fail"
            issue("CRITICAL", check_name, "Docker build failed for all contexts: " + " | ".join(build_errors))
            return issues

        tmp_logs = tempfile.mkdtemp(prefix=f"ccb-smoke-{task_name}-")
        run_cmd = [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{tests_dir}:/tests:ro",
            "-v",
            f"{tmp_logs}:/logs",
            image_tag,
            "bash",
            "-lc",
            (
                "set -e; mkdir -p /logs/agent /logs/verifier; "
                "printf 'smoke preflight\\n' > /logs/agent/solution.md; "
                "bash /tests/test.sh"
            ),
        ]
        run = subprocess.run(
            run_cmd,
            capture_output=True,
            text=True,
            timeout=verify_timeout,
            check=False,
        )
        reward_txt = Path(tmp_logs) / "verifier" / "reward.txt"
        reward_json = Path(tmp_logs) / "verifier" / "reward.json"
        has_reward = reward_txt.is_file() or reward_json.is_file()

        if run.returncode != 0:
            message = _shorten(run.stdout + "\n" + run.stderr)
            lower = message.lower()
            hard_failure_patterns = [
                "syntax error",
                "no such file or directory",
                "command not found",
                "traceback",
                "module not found",
                "modulenotfounderror",
            ]
            if any(p in lower for p in hard_failure_patterns):
                issue("CRITICAL", "smoke_verifier_exec_fail", f"Verifier execution failed: {message}")
                return issues
            if not has_reward:
                issue(
                    "CRITICAL",
                    "smoke_verifier_exec_fail",
                    f"Verifier failed before producing reward artifact: {message}",
                )
                return issues
            issue(
                "WARNING",
                "smoke_verifier_nonzero_with_reward",
                "Verifier returned non-zero but produced reward artifact (likely expected with dummy solution).",
            )

        if not has_reward:
            issue(
                "CRITICAL",
                "smoke_reward_missing",
                "Verifier ran but produced no reward.txt/reward.json in /logs/verifier",
            )
    except subprocess.TimeoutExpired:
        issue("CRITICAL", "smoke_verify_timeout", f"Verifier smoke exceeded timeout ({verify_timeout}s)")
    finally:
        subprocess.run(["docker", "image", "rm", "-f", image_tag], capture_output=True, text=True)

    return issues


def discover_task_dirs(suite: str | None = None, all_tasks: bool = False) -> list[Path]:
    """Find all task directories to validate."""
    dirs = []

    if suite:
        suite_dir = BENCHMARKS_DIR / suite
        if not suite_dir.is_dir():
            print(f"ERROR: Suite directory not found: {suite_dir}", file=sys.stderr)
            sys.exit(1)

        # Direct task dirs
        for entry in sorted(suite_dir.iterdir()):
            if entry.is_dir() and (entry / "task.toml").is_file():
                dirs.append(entry)
            # Check tasks/ subdirectory (swebenchpro)
            elif entry.name == "tasks" and entry.is_dir():
                for sub in sorted(entry.iterdir()):
                    if sub.is_dir() and (sub / "task.toml").is_file():
                        dirs.append(sub)
        return dirs

    if all_tasks:
        for bench_dir in sorted(BENCHMARKS_DIR.iterdir()):
            if not bench_dir.is_dir() or not bench_dir.name.startswith("ccb_"):
                continue
            for entry in sorted(bench_dir.iterdir()):
                if entry.is_dir() and (entry / "task.toml").is_file():
                    dirs.append(entry)
                elif entry.name == "tasks" and entry.is_dir():
                    for sub in sorted(entry.iterdir()):
                        if sub.is_dir() and (sub / "task.toml").is_file():
                            dirs.append(sub)
        return dirs

    return dirs


def format_table(all_issues: list[dict]) -> str:
    """Format issues as a human-readable report."""
    lines = []

    if not all_issues:
        lines.append("Pre-flight validation: ALL CHECKS PASSED")
        return "\n".join(lines)

    critical = [i for i in all_issues if i["severity"] == "CRITICAL"]
    warnings = [i for i in all_issues if i["severity"] == "WARNING"]
    infos = [i for i in all_issues if i["severity"] == "INFO"]

    lines.append(f"Pre-flight Validation: {len(all_issues)} issues found")
    lines.append(f"  CRITICAL: {len(critical)}")
    lines.append(f"  WARNING:  {len(warnings)}")
    lines.append(f"  INFO:     {len(infos)}")
    lines.append("")

    if critical:
        lines.append("CRITICAL (will cause run failures):")
        for i in critical:
            lines.append(f"  [{i['check']}] {i['benchmark']}/{i['task']}: {i['message']}")
        lines.append("")

    if warnings:
        lines.append("WARNING (may affect results):")
        for i in warnings:
            lines.append(f"  [{i['check']}] {i['benchmark']}/{i['task']}: {i['message']}")
        lines.append("")

    if infos:
        lines.append(f"INFO ({len(infos)} tasks not in selection registry — may be expected)")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Pre-flight validation of benchmark tasks."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--suite", help="Validate all tasks in a suite (e.g., ccb_pytorch)")
    group.add_argument("--task", type=Path, help="Validate a single task directory")
    group.add_argument("--all", action="store_true", help="Validate all benchmark tasks")
    parser.add_argument("--format", choices=["table", "json"], default="table")
    parser.add_argument("--critical-only", action="store_true",
                        help="Only show CRITICAL issues")
    parser.add_argument(
        "--smoke-runtime",
        action="store_true",
        help="Run Docker build + verifier smoke (no agent) for each task",
    )
    parser.add_argument(
        "--smoke-timeout-sec",
        type=int,
        default=300,
        help="Per-task timeout for --smoke-runtime (default: 300)",
    )
    parser.add_argument(
        "--smoke-build-timeout-sec",
        type=int,
        default=None,
        help="Docker build timeout (defaults to --smoke-timeout-sec)",
    )
    parser.add_argument(
        "--smoke-verify-timeout-sec",
        type=int,
        default=None,
        help="Verifier run timeout (defaults to --smoke-timeout-sec)",
    )
    args = parser.parse_args()

    selected_index = load_selected_tasks()

    if args.task:
        task_dir = args.task.resolve()
        if not task_dir.is_dir():
            print(f"ERROR: Not a directory: {task_dir}", file=sys.stderr)
            sys.exit(1)
        task_dirs = [task_dir]
    else:
        task_dirs = discover_task_dirs(suite=args.suite, all_tasks=args.all)

    if not task_dirs:
        print("No task directories found.", file=sys.stderr)
        sys.exit(1)

    all_issues = []
    for td in task_dirs:
        issues = validate_task(td, selected_index)
        if args.smoke_runtime:
            issues.extend(
                smoke_task_runtime(
                    td,
                    timeout_sec=args.smoke_timeout_sec,
                    build_timeout_sec=args.smoke_build_timeout_sec,
                    verify_timeout_sec=args.smoke_verify_timeout_sec,
                )
            )
        all_issues.extend(issues)

    if args.critical_only:
        all_issues = [i for i in all_issues if i["severity"] == "CRITICAL"]

    if args.format == "json":
        output = {
            "tasks_checked": len(task_dirs),
            "total_issues": len(all_issues),
            "critical": sum(1 for i in all_issues if i["severity"] == "CRITICAL"),
            "warning": sum(1 for i in all_issues if i["severity"] == "WARNING"),
            "info": sum(1 for i in all_issues if i["severity"] == "INFO"),
            "issues": all_issues,
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"Checked {len(task_dirs)} task directories.")
        print(format_table(all_issues))

    # Exit code
    critical_count = sum(1 for i in all_issues if i["severity"] == "CRITICAL")
    if critical_count > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
