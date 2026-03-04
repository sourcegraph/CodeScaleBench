#!/usr/bin/env python3
"""Smoke-test artifact-only verifiers without running an agent.

Builds Dockerfile.artifact_only, runs the verifier with mock artifacts,
and checks that reward.txt is produced with expected scores.

Usage:
    python3 scripts/smoke_artifact_verifier.py --task benchmarks/csb_sdlc_test/aspnetcore-code-review-001
    python3 scripts/smoke_artifact_verifier.py --all         # all tasks with Dockerfile.artifact_only
    python3 scripts/smoke_artifact_verifier.py --suite csb_sdlc_test
"""

import argparse
import json
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def find_artifact_tasks(suite: str | None = None) -> list[Path]:
    """Find all tasks that have a Dockerfile.artifact_only."""
    pattern = f"benchmarks/{suite or 'csb_*'}/*"
    tasks = []
    for task_dir in sorted(ROOT.glob(pattern)):
        if not task_dir.is_dir():
            continue
        dockerfile = task_dir / "environment" / "Dockerfile.artifact_only"
        if dockerfile.exists():
            tasks.append(task_dir)
    return tasks


def build_image(task_dir: Path, tag: str, timeout: int = 300) -> tuple[bool, str]:
    """Build Dockerfile.artifact_only and return (success, message)."""
    env_dir = task_dir / "environment"
    dockerfile = env_dir / "Dockerfile.artifact_only"

    if not dockerfile.exists():
        return False, f"No Dockerfile.artifact_only in {env_dir}"

    cmd = [
        "docker", "build",
        "-f", str(dockerfile),
        "-t", tag,
        str(env_dir),
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            return False, f"Docker build failed:\n{result.stderr[-500:]}"
        return True, "Build OK"
    except subprocess.TimeoutExpired:
        return False, f"Docker build timed out ({timeout}s)"


def run_verifier(
    tag: str,
    tests_dir: Path,
    mock_files: dict[str, str] | None = None,
    timeout: int = 120,
) -> tuple[bool, float | None, str]:
    """Run verifier in container, return (success, reward, details).

    Args:
        tag: Docker image tag
        tests_dir: Path to task's tests/ directory
        mock_files: Dict of {container_path: content} to create before running
        timeout: Seconds before killing container
    """
    with tempfile.TemporaryDirectory(prefix="smoke_verifier_") as tmpdir:
        logs_dir = Path(tmpdir) / "logs"
        logs_dir.mkdir()
        (logs_dir / "verifier").mkdir()
        (logs_dir / "agent").mkdir()

        # Build mock-file creation commands
        mock_cmds = []
        if mock_files:
            for path, content in mock_files.items():
                # Escape content for shell
                escaped = content.replace("'", "'\"'\"'")
                mock_cmds.append(f"mkdir -p $(dirname '{path}')")
                mock_cmds.append(f"cat > '{path}' << 'MOCK_EOF'\n{content}\nMOCK_EOF")

        mock_script = "\n".join(mock_cmds)

        run_script = f"""
set -e
mkdir -p /logs/verifier /logs/agent
{mock_script}
bash /tests/test.sh 2>/logs/verifier/test-stderr.txt
"""

        cmd = [
            "docker", "run", "--rm",
            "-v", f"{tests_dir}:/tests:ro",
            "-v", f"{logs_dir}:/logs",
            tag,
            "bash", "-c", run_script,
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
        except subprocess.TimeoutExpired:
            return False, None, f"Verifier timed out ({timeout}s)"

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        # Check reward file
        reward_txt = logs_dir / "verifier" / "reward.txt"
        reward_json = logs_dir / "verifier" / "reward.json"

        reward = None
        if reward_txt.exists():
            try:
                reward = float(reward_txt.read_text().strip())
            except ValueError:
                return False, None, f"reward.txt not a float: {reward_txt.read_text()!r}"
        elif reward_json.exists():
            try:
                data = json.loads(reward_json.read_text())
                reward = float(data.get("reward", data.get("score", 0)))
            except (json.JSONDecodeError, ValueError) as e:
                return False, None, f"reward.json parse error: {e}"
        else:
            # Read stderr for diagnostics
            stderr_file = logs_dir / "verifier" / "test-stderr.txt"
            stderr_content = ""
            if stderr_file.exists():
                stderr_content = stderr_file.read_text()[-500:]
            return False, None, (
                f"No reward file produced (exit={result.returncode})\n"
                f"stdout: {stdout[-300:]}\n"
                f"stderr: {stderr_content}"
            )

        # Read verifier stderr for scoring details
        stderr_file = logs_dir / "verifier" / "test-stderr.txt"
        details = ""
        if stderr_file.exists():
            details = stderr_file.read_text()

        return True, reward, details


def load_expected_defects(task_dir: Path) -> list[dict] | None:
    """Load expected_defects.json if it exists."""
    path = task_dir / "tests" / "expected_defects.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def make_detection_review(defects: list[dict]) -> str:
    """Create a review.json that matches all expected defect files (detection only)."""
    entries = []
    for d in defects:
        entries.append({
            "file": d["file"],
            "severity": d.get("severity", "medium"),
            "description": f"Smoke test detection for {d['id']}",
        })
    return json.dumps(entries, indent=2)


def smoke_test_task(
    task_dir: Path,
    build_timeout: int = 300,
    verify_timeout: int = 120,
    verbose: bool = False,
) -> dict:
    """Run the full smoke test for one task.

    Returns dict with: task, passed, tests (list of individual test results).
    """
    task_name = task_dir.name
    tag = f"ccb-smoke-artifact-{task_name}-{uuid.uuid4().hex[:8]}"
    tests_dir = task_dir / "tests"
    results = {"task": task_name, "passed": True, "tests": [], "tag": tag}

    # --- Test 0: Build ---
    ok, msg = build_image(task_dir, tag, timeout=build_timeout)
    results["tests"].append({
        "name": "docker_build",
        "passed": ok,
        "message": msg,
    })
    if not ok:
        results["passed"] = False
        return results

    try:
        # --- Test 1: No artifact → score 0.0 ---
        ok, reward, details = run_verifier(tag, tests_dir, timeout=verify_timeout)
        test1 = {
            "name": "no_artifact",
            "passed": ok and reward is not None and abs(reward) < 0.01,
            "reward": reward,
            "expected": 0.0,
            "message": "Verifier handles missing artifact gracefully",
        }
        if not ok:
            test1["message"] = f"FAILED: {details[:300]}"
            test1["passed"] = False
        elif reward is not None and abs(reward) > 0.01:
            test1["message"] = f"Expected ~0.0, got {reward}"
            test1["passed"] = False
        results["tests"].append(test1)
        if verbose and details:
            print(f"  [no_artifact] scoring: {details[:200]}", file=sys.stderr)

        # --- Test 2: Detection-only review.json → ~0.50 ---
        defects = load_expected_defects(task_dir)
        if defects:
            mock_review = make_detection_review(defects)
            mock_files = {"/workspace/review.json": mock_review}

            ok, reward, details = run_verifier(
                tag, tests_dir, mock_files=mock_files, timeout=verify_timeout
            )
            # Expected range: detection F1 should be ~1.0 (0.5 weight) and
            # some fix patterns may match base code. Range is intentionally
            # wide — the smoke test verifies the verifier RUNS, not scoring
            # calibration. Any score in [0.05, 0.95] shows the pipeline works.
            test2 = {
                "name": "detection_only",
                "passed": ok and reward is not None and 0.05 <= reward <= 0.95,
                "reward": reward,
                "expected_range": [0.05, 0.95],
                "message": "Detection-only review scores in expected range",
            }
            if not ok:
                test2["message"] = f"FAILED: {details[:300]}"
                test2["passed"] = False
            elif reward is not None and not (0.05 <= reward <= 0.95):
                test2["message"] = f"Expected 0.05-0.95, got {reward}"
                test2["passed"] = False
            results["tests"].append(test2)
            if verbose and details:
                print(f"  [detection_only] scoring: {details[:300]}", file=sys.stderr)

        # Update overall pass
        results["passed"] = all(t["passed"] for t in results["tests"])

    finally:
        # Clean up image
        subprocess.run(
            ["docker", "image", "rm", "-f", tag],
            capture_output=True, timeout=30,
        )

    return results


def main():
    parser = argparse.ArgumentParser(description="Smoke-test artifact-only verifiers")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--task", type=str, help="Path to a single task directory")
    group.add_argument("--suite", type=str, help="Suite name (e.g., csb_sdlc_test)")
    group.add_argument("--all", action="store_true", help="All tasks with Dockerfile.artifact_only")
    parser.add_argument("--build-timeout", type=int, default=300, help="Docker build timeout (s)")
    parser.add_argument("--verify-timeout", type=int, default=120, help="Verifier timeout (s)")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    if args.task:
        task_dir = Path(args.task).resolve()
        if not task_dir.exists():
            # Try relative to ROOT/benchmarks
            task_dir = ROOT / args.task
        if not task_dir.exists():
            print(f"Task directory not found: {args.task}", file=sys.stderr)
            sys.exit(1)
        tasks = [task_dir]
    elif args.suite:
        tasks = find_artifact_tasks(suite=args.suite)
    else:
        tasks = find_artifact_tasks()

    if not tasks:
        print("No tasks with Dockerfile.artifact_only found.", file=sys.stderr)
        sys.exit(1)

    print(f"Smoke-testing {len(tasks)} artifact-only task(s)...\n")
    all_results = []
    n_pass = 0
    n_fail = 0

    for task_dir in tasks:
        task_name = task_dir.name
        print(f"  {task_name}...", end=" ", flush=True)

        result = smoke_test_task(
            task_dir,
            build_timeout=args.build_timeout,
            verify_timeout=args.verify_timeout,
            verbose=args.verbose,
        )
        all_results.append(result)

        if result["passed"]:
            n_pass += 1
            tests_summary = ", ".join(
                f"{t['name']}={'OK' if t['passed'] else 'FAIL'}" for t in result["tests"]
            )
            print(f"PASS ({tests_summary})")
        else:
            n_fail += 1
            for t in result["tests"]:
                if not t["passed"]:
                    print(f"FAIL ({t['name']}: {t['message'][:100]})")
                    break

    print(f"\n{'='*50}")
    print(f"Results: {n_pass} passed, {n_fail} failed out of {len(tasks)}")

    if args.json:
        print(json.dumps(all_results, indent=2))

    sys.exit(1 if n_fail > 0 else 0)


if __name__ == "__main__":
    main()
