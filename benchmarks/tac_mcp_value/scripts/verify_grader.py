#!/usr/bin/env python3
"""
Verify TAC task graders are properly configured.

This script performs static verification to ensure each task has:
1. An instruction file (instruction.md)
2. A workspace/environment path (environment/Dockerfile)
3. A grading command (tests/test.sh)
4. A valid task.toml configuration

Does NOT execute the full evaluation - just verifies files exist and are valid.

Usage:
    python verify_grader.py [--task TASK_ID] [--all] [--verbose]

Examples:
    # Verify all tasks
    python verify_grader.py --all
    
    # Verify specific task
    python verify_grader.py --task tac-implement-hyperloglog
    
    # Verbose output
    python verify_grader.py --all --verbose
"""

import argparse
import os
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

try:
    import tomllib
except ImportError:
    import tomli as tomllib

# Base directory for this benchmark
BENCHMARK_DIR = Path(__file__).parent.parent

@dataclass
class VerificationResult:
    """Result of verifying a task."""
    task_id: str
    has_instruction: bool
    has_dockerfile: bool
    has_test_script: bool
    has_task_toml: bool
    task_toml_valid: bool
    test_script_executable: bool
    errors: list[str]
    warnings: list[str]
    
    @property
    def passed(self) -> bool:
        """Check if all critical verifications passed."""
        return (
            self.has_instruction and
            self.has_dockerfile and
            self.has_test_script and
            self.has_task_toml and
            self.task_toml_valid
        )

def verify_task_toml(task_dir: Path) -> tuple[bool, list[str]]:
    """Verify task.toml is valid and contains required fields."""
    task_toml = task_dir / "task.toml"
    errors = []
    
    if not task_toml.exists():
        return False, ["task.toml not found"]
    
    try:
        with open(task_toml, "rb") as f:
            config = tomllib.load(f)
    except Exception as e:
        return False, [f"Failed to parse task.toml: {e}"]
    
    # Check required sections
    required_sections = ["metadata", "task", "verification", "environment"]
    for section in required_sections:
        if section not in config:
            errors.append(f"Missing section: [{section}]")
    
    # Check metadata
    if "metadata" in config:
        if "name" not in config["metadata"]:
            errors.append("Missing metadata.name")
    
    # Check task
    if "task" in config:
        if "id" not in config["task"]:
            errors.append("Missing task.id")
        if "difficulty" not in config["task"]:
            errors.append("Missing task.difficulty")
    
    # Check verification
    if "verification" in config:
        if "command" not in config["verification"]:
            errors.append("Missing verification.command")
    
    return len(errors) == 0, errors

def verify_test_script(task_dir: Path) -> tuple[bool, bool, list[str]]:
    """Verify test.sh exists and is properly configured."""
    test_sh = task_dir / "tests" / "test.sh"
    errors = []
    exists = test_sh.exists()
    executable = False
    
    if not exists:
        return False, False, ["tests/test.sh not found"]
    
    # Check if executable
    executable = os.access(test_sh, os.X_OK)
    if not executable:
        errors.append("tests/test.sh is not executable (run: chmod +x tests/test.sh)")
    
    # Check content has shebang
    with open(test_sh) as f:
        content = f.read()
        if not content.startswith("#!/"):
            errors.append("tests/test.sh missing shebang (#!/bin/bash)")
    
    return exists, executable, errors

def verify_task(task_id: str, verbose: bool = False) -> Optional[VerificationResult]:
    """Verify a single task is properly configured."""
    task_dir = BENCHMARK_DIR / task_id
    
    if not task_dir.exists():
        return None
    
    errors = []
    warnings = []
    
    # Check instruction.md
    instruction_md = task_dir / "instruction.md"
    has_instruction = instruction_md.exists()
    if not has_instruction:
        errors.append("instruction.md not found")
    
    # Check Dockerfile
    dockerfile = task_dir / "environment" / "Dockerfile"
    has_dockerfile = dockerfile.exists()
    if not has_dockerfile:
        errors.append("environment/Dockerfile not found")
    
    # Check test script
    has_test_script, test_executable, test_errors = verify_test_script(task_dir)
    errors.extend(test_errors)
    
    # Check task.toml
    has_task_toml = (task_dir / "task.toml").exists()
    task_toml_valid, toml_errors = verify_task_toml(task_dir)
    errors.extend(toml_errors)
    
    # Optional checks (warnings)
    solution_dir = task_dir / "solution"
    if not solution_dir.exists():
        warnings.append("No solution/ directory (optional)")
    
    return VerificationResult(
        task_id=task_id,
        has_instruction=has_instruction,
        has_dockerfile=has_dockerfile,
        has_test_script=has_test_script,
        has_task_toml=has_task_toml,
        task_toml_valid=task_toml_valid,
        test_script_executable=test_executable,
        errors=errors,
        warnings=warnings,
    )

def get_all_task_ids() -> list[str]:
    """Get all task directory names."""
    task_ids = []
    for item in BENCHMARK_DIR.iterdir():
        if item.is_dir() and item.name.startswith("tac-"):
            task_ids.append(item.name)
    return sorted(task_ids)

def print_result(result: VerificationResult, verbose: bool = False):
    """Print verification result for a task."""
    status = "✓" if result.passed else "✗"
    print(f"\n{status} {result.task_id}")
    
    if verbose or not result.passed:
        print(f"  instruction.md: {'✓' if result.has_instruction else '✗'}")
        print(f"  environment/Dockerfile: {'✓' if result.has_dockerfile else '✗'}")
        print(f"  tests/test.sh: {'✓' if result.has_test_script else '✗'}")
        print(f"  task.toml: {'✓' if result.has_task_toml and result.task_toml_valid else '✗'}")
        
        if result.errors:
            print("  Errors:")
            for error in result.errors:
                print(f"    - {error}")
        
        if verbose and result.warnings:
            print("  Warnings:")
            for warning in result.warnings:
                print(f"    - {warning}")

def main():
    parser = argparse.ArgumentParser(
        description="Verify TAC task graders are properly configured"
    )
    parser.add_argument(
        "--task", "-t",
        help="Verify specific task by ID"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Verify all tasks"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output for all tasks"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON"
    )
    
    args = parser.parse_args()
    
    if args.task:
        result = verify_task(args.task, args.verbose)
        if result is None:
            print(f"Error: Task not found: {args.task}")
            return 1
        
        print_result(result, args.verbose)
        return 0 if result.passed else 1
    
    if args.all:
        task_ids = get_all_task_ids()
        
        if not task_ids:
            print("No TAC tasks found in benchmark directory")
            print(f"Looking in: {BENCHMARK_DIR}")
            return 1
        
        print(f"Verifying {len(task_ids)} TAC tasks...")
        print("=" * 60)
        
        results = []
        for task_id in task_ids:
            result = verify_task(task_id, args.verbose)
            if result:
                results.append(result)
                print_result(result, args.verbose)
        
        # Summary
        passed = sum(1 for r in results if r.passed)
        failed = len(results) - passed
        
        print("\n" + "=" * 60)
        print(f"Summary: {passed} passed, {failed} failed")
        
        if args.json:
            import json
            output = {
                "total": len(results),
                "passed": passed,
                "failed": failed,
                "tasks": [
                    {
                        "id": r.task_id,
                        "passed": r.passed,
                        "errors": r.errors,
                    }
                    for r in results
                ]
            }
            print("\nJSON Output:")
            print(json.dumps(output, indent=2))
        
        return 0 if failed == 0 else 1
    
    # Default: show help
    parser.print_help()
    return 0

if __name__ == "__main__":
    sys.exit(main())
