#!/usr/bin/env python3
"""Repo health gate: run required checks to keep tree clean and reduce drift.

Runs docs consistency, selection file validity, and (unless --quick) full task
preflight static checks. Exit 0 only if all required checks pass.

Usage:
    python3 scripts/repo_health.py           # Full health
    python3 scripts/repo_health.py --quick    # Docs + selection file only
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = REPO_ROOT / "configs" / "repo_health.json"


def load_contract() -> dict:
    """Load repo_health.json; return defaults if missing."""
    if CONTRACT_PATH.is_file():
        with open(CONTRACT_PATH) as f:
            return json.load(f)
    return {
        "checks": {
            "docs_consistency": {"script": "scripts/docs_consistency_check.py", "required": True},
            "task_preflight_static": {"script": "scripts/validate_tasks_preflight.py", "args": ["--all"], "required": True},
            "selection_file": {"script": None, "required": True},
        },
        "quick_checks": ["docs_consistency", "selection_file"],
    }


def check_selection_file(repo_root: Path) -> int:
    """Verify selected_benchmark_tasks.json exists and is valid JSON. Return 0 on success."""
    path = repo_root / "configs" / "selected_benchmark_tasks.json"
    if not path.is_file():
        print("  selection_file: FAILED (file not found)")
        return 1
    try:
        with open(path) as f:
            json.load(f)
    except json.JSONDecodeError as e:
        print(f"  selection_file: FAILED (invalid JSON: {e})")
        return 1
    print("  selection_file: OK")
    return 0


def check_launch_policy(repo_root: Path) -> int:
    """Reject raw harbor run invocations in launcher scripts outside the shared wrapper."""
    configs_dir = repo_root / "configs"
    offenders: list[str] = []
    raw_harbor_pattern = re.compile(r"(^|[^\w])harbor run([^\w]|$)")

    for script_path in sorted(configs_dir.glob("*.sh")):
        if script_path.name == "_common.sh":
            continue
        for lineno, raw_line in enumerate(script_path.read_text().splitlines(), start=1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("echo ") or stripped.startswith('echo"') or stripped.startswith("printf "):
                continue
            if raw_harbor_pattern.search(raw_line):
                offenders.append(f"{script_path.relative_to(repo_root)}:{lineno}")

    if offenders:
        print("  launch_policy: FAILED")
        print("    Raw `harbor run` is not allowed in configs/*.sh outside configs/_common.sh.")
        for offender in offenders[:15]:
            print(f"    {offender}")
        return 1

    print("  launch_policy: OK")
    return 0


def run_script_check(name: str, script: str, args: list[str], repo_root: Path) -> int:
    """Run a script; return its exit code."""
    cmd = [sys.executable, str(repo_root / script)] + (args or [])
    result = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  {name}: FAILED")
        if result.stdout:
            for line in result.stdout.strip().splitlines()[:15]:
                print(f"    {line}")
        if result.stderr:
            for line in result.stderr.strip().splitlines()[:5]:
                print(f"    stderr: {line}")
    else:
        print(f"  {name}: OK")
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Only run quick checks (docs_consistency, selection_file)",
    )
    parser.add_argument(
        "--contract",
        type=Path,
        default=CONTRACT_PATH,
        help="Path to repo_health.json",
    )
    args = parser.parse_args()

    contract = load_contract()
    checks = contract.get("checks") or {}
    quick_list = contract.get("quick_checks") or ["docs_consistency", "selection_file"]

    to_run = quick_list if args.quick else list(checks.keys())
    failures: list[str] = []

    print("Repo health gate")
    print("-" * 40)

    for name in to_run:
        spec = checks.get(name)
        if not spec:
            continue
        required = spec.get("required", True)

        if name == "selection_file":
            code = check_selection_file(REPO_ROOT)
        elif name == "launch_policy":
            code = check_launch_policy(REPO_ROOT)
        elif spec.get("script"):
            script = spec["script"]
            script_args = spec.get("args") or []
            code = run_script_check(name, script, script_args, REPO_ROOT)
        else:
            continue

        if code != 0 and required:
            failures.append(name)

    print("-" * 40)
    if failures:
        print(f"FAILED: {', '.join(failures)}")
        return 1
    print("All required checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
