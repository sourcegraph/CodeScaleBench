#!/usr/bin/env python3
"""Validate org-scale task instances using the fail2pass gate.

Ensures every task is non-degenerate:
  - Gold oracle answer scores > 0 (task is solvable)
  - Empty answer scores exactly 0 (task rejects garbage)

Reports per-task status:
  VALID            — gold > 0 AND empty == 0
  DEGENERATE_PASS  — empty > 0 (task gives points for nothing)
  DEGENERATE_FAIL  — gold == 0 (task impossible or oracle broken)
  BROKEN           — missing files or parse errors

Usage:
    python3 validate_mcp_task_instance.py --task-dir <path> [--verbose] [--fix]
    python3 validate_mcp_task_instance.py --task-dir dir1 --task-dir dir2

Exit codes:
    0 — all tasks VALID
    1 — at least one non-VALID task
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

# Add parent to sys.path for oracle_checks import
_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))
from csb_metrics.oracle_checks import run_all_checks


def _find_task_spec(task_dir: Path) -> Path:
    """Find task_spec.json in a task directory."""
    candidates = [
        task_dir / "task_spec.json",
        task_dir / "tests" / "task_spec.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(f"task_spec.json not found in {task_dir}")


def _find_oracle_answer(task_dir: Path) -> Path:
    """Find oracle_answer.json in a task directory."""
    candidates = [
        task_dir / "tests" / "oracle_answer.json",
        task_dir / "oracle_answer.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(f"oracle_answer.json not found in {task_dir}")


def _make_empty_answer() -> str:
    """Create a temporary empty answer file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".json", prefix="empty_answer_")
    with os.fdopen(fd, "w") as f:
        json.dump({}, f)
    return path


def _generate_stub_oracle(task_spec_path: Path, output_path: Path) -> None:
    """Generate a stub oracle_answer.json from task_spec.json oracle definitions."""
    with open(task_spec_path) as f:
        spec = json.load(f)

    oracle = spec.get("artifacts", {}).get("oracle", {})

    stub = {
        "files": oracle.get("required_files", []),
        "symbols": oracle.get("required_symbols", []),
        "chain": [],
        "text": "",
    }

    # Build chain from first dependency chain
    chains = oracle.get("dependency_chains", [])
    if chains:
        stub["chain"] = chains[0].get("steps", [])

    # Build text from all repo/path/symbol references for provenance checks
    refs = set()
    for f in stub["files"]:
        refs.add(f.get("repo", ""))
        refs.add(f.get("path", ""))
    for s in stub["symbols"]:
        refs.add(s.get("repo", ""))
        refs.add(s.get("path", ""))
        refs.add(s.get("symbol", ""))
    stub["text"] = " ".join(sorted(r for r in refs if r))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(stub, f, indent=2)


def validate_task(task_dir: Path, verbose: bool = False, fix: bool = False) -> str:
    """Validate a single task directory.

    Returns one of: VALID, DEGENERATE_PASS, DEGENERATE_FAIL, BROKEN
    """
    task_dir = Path(task_dir)

    # Find task_spec
    try:
        spec_path = _find_task_spec(task_dir)
    except FileNotFoundError as e:
        if verbose:
            print(f"  BROKEN: {e}", file=sys.stderr)
        return "BROKEN"

    # Find or generate oracle answer
    try:
        oracle_path = _find_oracle_answer(task_dir)
    except FileNotFoundError:
        if fix:
            oracle_path = task_dir / "tests" / "oracle_answer.json"
            try:
                _generate_stub_oracle(spec_path, oracle_path)
                if verbose:
                    print(f"  Generated stub: {oracle_path}", file=sys.stderr)
            except Exception as e:
                if verbose:
                    print(f"  BROKEN: Cannot generate stub: {e}", file=sys.stderr)
                return "BROKEN"
        else:
            if verbose:
                print(f"  BROKEN: oracle_answer.json not found (use --fix to generate stub)", file=sys.stderr)
            return "BROKEN"

    # Run gold answer check
    try:
        gold_result = run_all_checks(str(oracle_path), str(spec_path))
        gold_score = gold_result.get("composite_score", 0.0)
    except Exception as e:
        if verbose:
            print(f"  BROKEN: Gold check error: {e}", file=sys.stderr)
        return "BROKEN"

    if verbose:
        print(f"  Gold score: {gold_score:.4f}", file=sys.stderr)

    # Run empty answer check
    empty_path = _make_empty_answer()
    try:
        empty_result = run_all_checks(empty_path, str(spec_path))
        empty_score = empty_result.get("composite_score", 0.0)
    except Exception as e:
        if verbose:
            print(f"  BROKEN: Empty check error: {e}", file=sys.stderr)
        return "BROKEN"
    finally:
        os.unlink(empty_path)

    if verbose:
        print(f"  Empty score: {empty_score:.4f}", file=sys.stderr)

    # Classify
    if gold_score > 0 and empty_score == 0:
        return "VALID"
    elif empty_score > 0:
        return "DEGENERATE_PASS"
    elif gold_score == 0:
        return "DEGENERATE_FAIL"
    else:
        return "BROKEN"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate org-scale task instances (fail2pass gate)."
    )
    parser.add_argument(
        "--task-dir", action="append", required=True,
        help="Path to task directory (can be specified multiple times)."
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print detailed check results."
    )
    parser.add_argument(
        "--fix", action="store_true",
        help="Generate stub oracle_answer.json from task_spec.json if missing."
    )
    args = parser.parse_args()

    results = {}
    for task_dir in args.task_dir:
        task_path = Path(task_dir)
        task_name = task_path.name
        print(f"{task_name}:", end=" ")
        status = validate_task(task_path, verbose=args.verbose, fix=args.fix)
        results[task_name] = status
        print(status)

    # Summary
    total = len(results)
    valid = sum(1 for s in results.values() if s == "VALID")
    degen_pass = sum(1 for s in results.values() if s == "DEGENERATE_PASS")
    degen_fail = sum(1 for s in results.values() if s == "DEGENERATE_FAIL")
    broken = sum(1 for s in results.values() if s == "BROKEN")

    print(f"\nSummary: {valid}/{total} VALID, "
          f"{degen_pass} DEGENERATE_PASS, "
          f"{degen_fail} DEGENERATE_FAIL, "
          f"{broken} BROKEN")

    sys.exit(0 if valid == total else 1)


if __name__ == "__main__":
    main()
