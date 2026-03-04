#!/usr/bin/env python3
"""Golden-solution validation for Dockerfile.artifact_only images.

Builds each task's Dockerfile.artifact_only, injects the known-correct
solution, runs the verifier, and checks that reward ≈ 1.0.

Handles five solution types:
  1. solve.sh          — SWE-bench Pro tasks (csb_sdlc_fix): apply gold patch
  2. oracle_answer.json — MCP-unique tasks: copy as /workspace/answer.json
  3. ground_truth.json  — SDLC oracle tasks: synthesize perfect report from patterns
  4. expected_defects   — Code review tasks: detection-only review.json
  5. reference_fix      — Navprove tasks: Phase 2 only (partial)

Usage:
    python3 scripts/validate_artifact_golden.py --all
    python3 scripts/validate_artifact_golden.py --suite csb_sdlc_fix
    python3 scripts/validate_artifact_golden.py --task benchmarks/csb_sdlc_fix/flipt-trace-sampling-fix-001
    python3 scripts/validate_artifact_golden.py --all --json --output results.json
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS = ROOT / "benchmarks"


# ---------------------------------------------------------------------------
# Task discovery
# ---------------------------------------------------------------------------

def find_tasks(suite: str | None = None, task_path: str | None = None) -> list[Path]:
    """Find tasks with Dockerfile.artifact_only."""
    if task_path:
        p = Path(task_path).resolve()
        if not p.exists():
            p = ROOT / task_path
        return [p] if p.exists() else []

    pattern = f"csb_sdlc_{suite}" if suite else "csb_*"
    tasks = []
    for task_dir in sorted(BENCHMARKS.glob(f"{pattern}/*/environment")):
        if task_dir.is_dir() and (task_dir / "Dockerfile.artifact_only").exists():
            tasks.append(task_dir.parent)
    return tasks


# ---------------------------------------------------------------------------
# Solution type classification
# ---------------------------------------------------------------------------

def classify_task(task_dir: Path) -> str:
    """Classify how to inject the golden solution."""
    if (task_dir / "solution" / "solve.sh").exists():
        return "solve_sh"
    if (task_dir / "tests" / "oracle_answer.json").exists():
        return "oracle_answer"
    if (task_dir / "tests" / "ground_truth.json").exists():
        return "ground_truth"
    if (task_dir / "tests" / "expected_defects.json").exists():
        return "expected_defects"
    if (task_dir / "tests" / "reference_fix.patch").exists():
        return "reference_fix"
    return "unknown"


# ---------------------------------------------------------------------------
# Solution generators — produce {container_path: content} for mock injection
# ---------------------------------------------------------------------------

def solution_solve_sh(task_dir: Path) -> tuple[str, dict[str, str]]:
    """For SWE-bench Pro: inject solve.sh and run it before verifier."""
    solve_content = (task_dir / "solution" / "solve.sh").read_text()
    # solve.sh is a script the container runs; we inject it and execute it
    return "solve_sh", {"/tmp/golden_solve.sh": solve_content}


def solution_oracle_answer(task_dir: Path) -> tuple[str, dict[str, str]]:
    """For MCP-unique: copy oracle_answer.json as /workspace/answer.json."""
    content = (task_dir / "tests" / "oracle_answer.json").read_text()
    return "oracle_answer", {"/workspace/answer.json": content}


def _solution_ground_truth_filelist(task_dir: Path, file_list: list) -> tuple[str, dict[str, str]]:
    """Handle list-format ground_truth.json (file-list impact tasks).

    These tasks expect /workspace/submission.json with a list of file paths.
    """
    # Determine output path from test.sh
    test_sh = task_dir / "tests" / "test.sh"
    output_path = "/workspace/submission.json"  # default for impact tasks
    if test_sh.exists():
        text = test_sh.read_text()
        # Look for the submission file path
        m = re.search(r'[ !]-f\s+(/\S+\.json)', text)
        if m:
            output_path = m.group(1)

    content = json.dumps(file_list, indent=2)
    return "ground_truth", {output_path: content}


def solution_ground_truth(task_dir: Path) -> tuple[str, dict[str, str]]:
    """Synthesize a perfect report from ground_truth.json patterns."""
    gt = json.loads((task_dir / "tests" / "ground_truth.json").read_text())

    # Handle list-format ground_truth.json (file-list tasks like impact analysis)
    if isinstance(gt, list):
        return _solution_ground_truth_filelist(task_dir, gt)

    lines = ["# Analysis Report\n"]

    # Required findings — need ANY pattern to match per item
    for item in gt.get("required_findings", []):
        lines.append(f"## {item['description']}")
        # Include patterns as literal text (de-escaped) to ensure regex match
        for p in item.get("patterns", []):
            # Convert regex to plain text: remove common anchors/escapes
            plain = p.replace("\\.", ".").replace("\\(", "(").replace("\\)", ")")
            plain = plain.replace("\\{", "{").replace("\\}", "}")
            plain = plain.replace("\\[", "[").replace("\\]", "]")
            lines.append(f"- {plain}")
        lines.append("")

    # File references — need ANY pattern to match per item
    for item in gt.get("file_references", []):
        lines.append(f"### {item['description']}")
        for p in item.get("patterns", []):
            plain = p.replace("\\.", ".").replace("\\(", "(").replace("\\)", ")")
            lines.append(f"- File: {plain}")
        lines.append("")

    # Causal chain — need ALL patterns to match per item
    for item in gt.get("causal_chain", []):
        lines.append(f"### Causal: {item['description']}")
        for p in item.get("patterns", []):
            plain = p.replace("\\.", ".").replace("\\(", "(").replace("\\)", ")")
            lines.append(f"  {plain}")
        lines.append("")

    # Negative checks — do NOT include these patterns
    # Just add a note to keep the report long enough without triggering negatives
    if gt.get("negative_checks"):
        lines.append("## Additional Notes")
        lines.append("This analysis focuses on the confirmed findings above.")
        lines.append("")

    report = "\n".join(lines)

    # Determine the report path from test.sh (defaults to /logs/agent/onboarding.md)
    test_sh = task_dir / "tests" / "test.sh"
    report_path = "/logs/agent/onboarding.md"  # default
    if test_sh.exists():
        text = test_sh.read_text()
        m = re.search(r'REPORT_PATH="\$\{REPORT_PATH:-([^}]+)\}"', text)
        if m:
            report_path = m.group(1)
        else:
            m = re.search(r'REPORT_PATH="([^"]+)"', text)
            if m:
                report_path = m.group(1)

    return "ground_truth", {report_path: report}


def solution_expected_defects(task_dir: Path) -> tuple[str, dict[str, str]]:
    """For code review: create detection-only review.json."""
    defects = json.loads((task_dir / "tests" / "expected_defects.json").read_text())
    review = []
    for d in defects:
        entry = {
            "file": d["file"],
            "severity": d.get("severity", "medium"),
            "description": d.get("description", f"Defect {d['id']}"),
            "line_start": d.get("line_start"),
            "line_end": d.get("line_end"),
            "defect_type": d.get("defect_type", "bug"),
        }
        review.append(entry)
    return "expected_defects", {"/workspace/review.json": json.dumps(review, indent=2)}


def get_solution(task_dir: Path) -> tuple[str, dict[str, str]]:
    """Get the golden solution files for a task."""
    stype = classify_task(task_dir)
    if stype == "solve_sh":
        return solution_solve_sh(task_dir)
    elif stype == "oracle_answer":
        return solution_oracle_answer(task_dir)
    elif stype == "ground_truth":
        return solution_ground_truth(task_dir)
    elif stype == "expected_defects":
        return solution_expected_defects(task_dir)
    elif stype == "reference_fix":
        # Navprove: can't fully validate (needs agent-written test)
        return "reference_fix", {}
    return "unknown", {}


# ---------------------------------------------------------------------------
# Docker build + run
# ---------------------------------------------------------------------------

def build_image(task_dir: Path, tag: str, timeout: int = 600) -> tuple[bool, str]:
    """Build Dockerfile.artifact_only."""
    env_dir = task_dir / "environment"
    dockerfile = env_dir / "Dockerfile.artifact_only"
    cmd = ["docker", "build", "-f", str(dockerfile), "-t", tag, str(env_dir)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode != 0:
            return False, f"Build failed:\n{result.stderr[-500:]}"
        return True, "Build OK"
    except subprocess.TimeoutExpired:
        return False, f"Build timeout ({timeout}s)"


def run_golden_test(
    tag: str,
    task_dir: Path,
    solution_type: str,
    mock_files: dict[str, str],
    timeout: int = 300,
) -> tuple[bool, float | None, str]:
    """Run verifier with golden solution injected."""
    tests_dir = task_dir / "tests"

    # Determine which test script to use
    eval_sh = tests_dir / "eval.sh"
    test_sh = tests_dir / "test.sh"
    if eval_sh.exists():
        verifier_script = "bash /tests/eval.sh"
    elif test_sh.exists():
        verifier_script = "bash /tests/test.sh"
    else:
        return False, None, "No eval.sh or test.sh found"

    with tempfile.TemporaryDirectory(prefix="golden_verify_") as tmpdir:
        logs_dir = Path(tmpdir) / "logs"
        logs_dir.mkdir()
        (logs_dir / "verifier").mkdir()
        (logs_dir / "agent").mkdir()

        # Write mock files to host tmpdir, then mount and copy inside container.
        # This avoids OS argument-list-too-long for large files (e.g. solve.sh).
        staging_dir = Path(tmpdir) / "staging"
        staging_dir.mkdir()
        inject_cmds = []
        for path, content in mock_files.items():
            # Write each file to staging dir with a safe filename
            safe_name = path.replace("/", "__").lstrip("_")
            (staging_dir / safe_name).write_text(content)
            inject_cmds.append(f"mkdir -p $(dirname '{path}')")
            inject_cmds.append(f"cp '/tmp/_staging/{safe_name}' '{path}'")

        inject_script = "\n".join(inject_cmds)

        # For solve.sh tasks, run the solve script first
        solve_cmd = ""
        if solution_type == "solve_sh":
            solve_cmd = "bash /tmp/golden_solve.sh 2>/logs/verifier/solve-stderr.txt || true\n"

        run_script = f"""
set -e
mkdir -p /logs/verifier /logs/agent
{inject_script}
{solve_cmd}
{verifier_script} 2>/logs/verifier/test-stderr.txt || true
"""

        cmd = [
            "docker", "run", "--rm",
            "-v", f"{tests_dir}:/tests:ro",
            "-v", f"{logs_dir}:/logs",
            "-v", f"{staging_dir}:/tmp/_staging:ro",
            tag,
            "bash", "-c", run_script,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, None, f"Verifier timeout ({timeout}s)"

        # Read reward
        reward_txt = logs_dir / "verifier" / "reward.txt"
        reward_json_f = logs_dir / "verifier" / "reward.json"

        reward = None
        if reward_txt.exists():
            try:
                reward = float(reward_txt.read_text().strip())
            except ValueError:
                return False, None, f"reward.txt not a float: {reward_txt.read_text()!r}"
        elif reward_json_f.exists():
            try:
                data = json.loads(reward_json_f.read_text())
                reward = float(data.get("reward", data.get("score", 0)))
            except (json.JSONDecodeError, ValueError) as e:
                return False, None, f"reward.json parse error: {e}"
        else:
            stderr_file = logs_dir / "verifier" / "test-stderr.txt"
            stderr_content = ""
            if stderr_file.exists():
                stderr_content = stderr_file.read_text()[-500:]
            return False, None, (
                f"No reward file (exit={result.returncode})\n"
                f"stdout: {result.stdout[-300:]}\n"
                f"stderr: {stderr_content}"
            )

        # Read verifier details
        details = ""
        stderr_file = logs_dir / "verifier" / "test-stderr.txt"
        if stderr_file.exists():
            details = stderr_file.read_text()

        return True, reward, details


# ---------------------------------------------------------------------------
# Main validation
# ---------------------------------------------------------------------------

def validate_task(
    task_dir: Path,
    build_timeout: int = 600,
    verify_timeout: int = 300,
    verbose: bool = False,
) -> dict:
    """Validate one task with golden solution."""
    task_name = task_dir.name
    suite = task_dir.parent.name
    tag = f"ccb-golden-{task_name[:40]}-{uuid.uuid4().hex[:8]}"

    solution_type, mock_files = get_solution(task_dir)

    result = {
        "task": task_name,
        "suite": suite,
        "solution_type": solution_type,
        "build_ok": False,
        "verifier_ok": False,
        "reward": None,
        "expected_reward": (
            0.95 if solution_type == "oracle_answer"
            else 0.90 if solution_type == "solve_sh"
            else 0.70 if solution_type == "ground_truth"
            else 0.05 if solution_type == "expected_defects"  # detection-only
            else 0.0
        ),
        "passed": False,
        "message": "",
    }

    if solution_type == "unknown":
        result["message"] = "No solution type detected — skipped"
        return result

    if solution_type == "reference_fix" and not mock_files:
        result["message"] = "Navprove: needs agent-written test — skipped"
        return result

    # Build
    ok, msg = build_image(task_dir, tag, timeout=build_timeout)
    result["build_ok"] = ok
    if not ok:
        result["message"] = f"Build failed: {msg}"
        cleanup_image(tag)
        return result

    try:
        # Run with golden solution
        ok, reward, details = run_golden_test(
            tag, task_dir, solution_type, mock_files, timeout=verify_timeout
        )
        result["verifier_ok"] = ok
        result["reward"] = reward

        if not ok:
            result["message"] = f"Verifier error: {details[:300]}"
        elif reward is None:
            result["message"] = "No reward produced"
        elif reward >= result["expected_reward"]:
            result["passed"] = True
            result["message"] = f"reward={reward:.2f} >= {result['expected_reward']}"
        else:
            result["message"] = f"reward={reward:.2f} < {result['expected_reward']} expected"

        if verbose and details:
            print(f"    Details: {details[:200]}", file=sys.stderr)

    finally:
        cleanup_image(tag)

    return result


def cleanup_image(tag: str):
    """Remove Docker image."""
    subprocess.run(
        ["docker", "image", "rm", "-f", tag],
        capture_output=True, timeout=30,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Golden-solution validation for artifact_only Dockerfiles"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--task", type=str, help="Single task path")
    group.add_argument("--suite", type=str, help="Suite name (e.g., csb_sdlc_fix)")
    group.add_argument("--all", action="store_true", help="All tasks")
    parser.add_argument("--build-timeout", type=int, default=600)
    parser.add_argument("--verify-timeout", type=int, default=300)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", action="store_true", help="Output JSON results")
    parser.add_argument("--output", type=str, help="Write JSON to file")
    parser.add_argument(
        "--skip-types", nargs="*", default=[],
        help="Solution types to skip (e.g., reference_fix unknown)"
    )
    args = parser.parse_args()

    tasks = find_tasks(suite=args.suite, task_path=args.task) if not args.all else find_tasks()

    if not tasks:
        print("No tasks found.", file=sys.stderr)
        sys.exit(1)

    # Classify and show plan
    by_type: dict[str, list[Path]] = {}
    for t in tasks:
        stype = classify_task(t)
        by_type.setdefault(stype, []).append(t)

    print(f"Golden-solution validation: {len(tasks)} tasks\n")
    for stype, task_list in sorted(by_type.items()):
        skip_marker = " [SKIP]" if stype in args.skip_types else ""
        print(f"  {stype}: {len(task_list)} tasks{skip_marker}")
    print()

    all_results = []
    counts = {"passed": 0, "failed": 0, "skipped": 0, "build_fail": 0}

    for task_dir in tasks:
        task_name = task_dir.name
        stype = classify_task(task_dir)

        if stype in args.skip_types:
            counts["skipped"] += 1
            continue

        print(f"  {task_name} ({stype})...", end=" ", flush=True)

        try:
            result = validate_task(
                task_dir,
                build_timeout=args.build_timeout,
                verify_timeout=args.verify_timeout,
                verbose=args.verbose,
            )
        except Exception as e:
            result = {
                "task": task_name,
                "suite": task_dir.parent.name,
                "solution_type": stype,
                "build_ok": False,
                "verifier_ok": False,
                "reward": None,
                "expected_reward": 0,
                "passed": False,
                "message": f"CRASH: {type(e).__name__}: {e}",
            }
        all_results.append(result)

        if result["message"].startswith("CRASH:"):
            counts["failed"] += 1
            print(f"CRASH ({result['message'][:80]})")
        elif not result["build_ok"] and result["solution_type"] not in ("unknown", "reference_fix"):
            counts["build_fail"] += 1
            print(f"BUILD FAIL ({result['message'][:80]})")
        elif result["passed"]:
            counts["passed"] += 1
            print(f"PASS (reward={result['reward']:.2f})")
        elif result["solution_type"] in ("unknown", "reference_fix") and not result["build_ok"]:
            counts["skipped"] += 1
            print(f"SKIP ({result['message'][:60]})")
        else:
            counts["failed"] += 1
            reward_str = f"reward={result['reward']:.2f}" if result['reward'] is not None else "no reward"
            print(f"FAIL ({reward_str}, {result['message'][:60]})")

    print(f"\n{'='*60}")
    print(f"Results: {counts['passed']} passed, {counts['failed']} failed, "
          f"{counts['build_fail']} build failures, {counts['skipped']} skipped")
    print(f"Total: {len(tasks)} tasks")

    if args.json or args.output:
        summary = {
            "total_tasks": len(tasks),
            "counts": counts,
            "results": all_results,
        }
        json_str = json.dumps(summary, indent=2)
        if args.output:
            Path(args.output).write_text(json_str)
            print(f"\nJSON results written to {args.output}")
        if args.json:
            print(json_str)

    sys.exit(1 if counts["failed"] > 0 or counts["build_fail"] > 0 else 0)


if __name__ == "__main__":
    main()
