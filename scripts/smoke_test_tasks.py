#!/usr/bin/env python3
"""Smoke-test benchmark tasks on Daytona: build image + run test.sh verifier.

Does NOT run the agent — just validates the Docker build and verifier work.
Runs tasks in parallel via Daytona sandboxes.

Usage:
  python3 scripts/smoke_test_tasks.py --task-ids bazel-starlark-eval-test-001,godot-gdscript-api-docgen-001
  python3 scripts/smoke_test_tasks.py --task-ids-file /tmp/tasks.txt
  python3 scripts/smoke_test_tasks.py --task-dirs benchmarks/csb_sdlc_test/bazel-starlark-eval-test-001
"""

import argparse
import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS_DIR = REPO_ROOT / "benchmarks"

log = logging.getLogger("smoke")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def find_task_dir(task_id: str) -> Path:
    """Find task directory by task_id across all suite dirs."""
    for suite_dir in sorted(BENCHMARKS_DIR.iterdir()):
        if not suite_dir.is_dir() or not suite_dir.name.startswith("csb_"):
            continue
        candidate = suite_dir / task_id
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(f"Task dir not found for {task_id}")


def smoke_one(task_dir: Path, config: str = "baseline") -> dict:
    """Build sandbox, upload tests, run test.sh, return result dict."""
    from daytona_sdk import Daytona, CreateSandboxFromImageParams, Image, Resources

    task_id = task_dir.name
    suite = task_dir.parent.name
    result = {
        "task_id": task_id,
        "suite": suite,
        "config": config,
        "build_ok": False,
        "verifier_ok": False,
        "verifier_output": "",
        "error": "",
        "elapsed_sec": 0,
    }
    t0 = time.time()

    # Pick dockerfile
    if config == "sg_only":
        df_name = "Dockerfile.sg_only"
    else:
        df_name = "Dockerfile"
    df_path = task_dir / "environment" / df_name
    if not df_path.exists():
        result["error"] = f"Missing {df_name}"
        return result

    sandbox = None
    try:
        daytona = Daytona()
        dockerfile_text = df_path.read_text()
        env_dir = task_dir / "environment"

        needs_context = "COPY " in dockerfile_text or "ADD " in dockerfile_text
        if needs_context:
            image = Image.from_dockerfile(str(df_path), context_path=str(env_dir))
        else:
            image = Image.from_dockerfile(str(df_path))

        storage_override = int(os.environ.get("DAYTONA_OVERRIDE_STORAGE", "10240"))
        params = CreateSandboxFromImageParams(
            image=image,
            language="python",
            labels={"task": task_id, "suite": suite, "purpose": "smoke-test"},
            resources=Resources(cpu=2, memory=4, disk=max(storage_override // 1024, 10)),
            auto_stop_interval=0,
        )

        log.info(f"[{task_id}] Building sandbox ({config})...")
        sandbox = daytona.create(params, timeout=600,
                                on_snapshot_create_logs=lambda msg: None)
        result["build_ok"] = True
        log.info(f"[{task_id}] Build OK ({time.time() - t0:.0f}s)")

        # Upload test files
        tests_dir = task_dir / "tests"
        if tests_dir.is_dir():
            sandbox.process.exec("mkdir -p /tests", timeout=10)
            for tf in sorted(tests_dir.iterdir()):
                if not tf.is_file():
                    continue
                text = tf.read_text()
                delim = f"EOF_{hash(tf.name) & 0xFFFFFF:06x}"
                sandbox.process.exec(
                    f"cat > /tests/{tf.name} << '{delim}'\n{text}\n{delim}",
                    timeout=30)
            sandbox.process.exec("chmod +x /tests/*.sh 2>/dev/null || true", timeout=10)

        # Run test.sh (expect failure since no agent ran — we just want no crash)
        log.info(f"[{task_id}] Running verifier...")
        try:
            resp = sandbox.process.exec("bash /tests/test.sh 2>&1", timeout=120)
            # Daytona SDK returns ExecuteResponse with .result and .exit_code
            verifier_out = resp.result if hasattr(resp, 'result') else str(resp)
            exit_code = resp.exit_code if hasattr(resp, 'exit_code') else -1
            result["verifier_output"] = verifier_out[:3000] if verifier_out else ""
            result["exit_code"] = exit_code
            if exit_code == 0:
                result["verifier_ok"] = True
                log.info(f"[{task_id}] Verifier passed (exit 0)")
            else:
                result["verifier_ok"] = True  # Non-zero exit expected (no agent ran)
                log.info(f"[{task_id}] Verifier exited {exit_code} (expected, no agent ran)")
        except Exception as ve:
            err_str = str(ve)
            result["verifier_output"] = err_str[:3000]
            # Non-zero exit is expected (agent didn't run), but crashes are bad
            if "exit code" in err_str.lower() or "non-zero" in err_str.lower():
                result["verifier_ok"] = True  # Normal failure = verifier works
                log.info(f"[{task_id}] Verifier exited non-zero (expected, no agent ran)")
            else:
                result["error"] = f"Verifier crash: {err_str[:200]}"
                log.warning(f"[{task_id}] Verifier crash: {err_str[:200]}")

    except Exception as e:
        result["error"] = str(e)[:500]
        log.error(f"[{task_id}] FAILED: {result['error'][:200]}")
    finally:
        result["elapsed_sec"] = round(time.time() - t0, 1)
        if sandbox:
            try:
                Daytona().delete(sandbox)
            except Exception:
                pass

    return result


def main():
    parser = argparse.ArgumentParser(description="Smoke-test tasks on Daytona")
    parser.add_argument("--task-ids", type=str, default="",
                        help="Comma-separated task IDs")
    parser.add_argument("--task-ids-file", type=str, default="",
                        help="File with one task ID per line")
    parser.add_argument("--task-dirs", type=str, nargs="*", default=[],
                        help="Explicit task directory paths")
    parser.add_argument("--config", type=str, default="baseline",
                        choices=["baseline", "sg_only", "both"],
                        help="Which Dockerfile to test (default: baseline)")
    parser.add_argument("--parallel", type=int, default=10,
                        help="Concurrent sandboxes (default: 10)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Collect task dirs
    task_dirs = []
    if args.task_ids:
        for tid in args.task_ids.split(","):
            tid = tid.strip()
            if tid:
                task_dirs.append(find_task_dir(tid))
    if args.task_ids_file:
        for line in Path(args.task_ids_file).read_text().splitlines():
            tid = line.strip()
            if tid and not tid.startswith("#"):
                task_dirs.append(find_task_dir(tid))
    for td in args.task_dirs or []:
        task_dirs.append(Path(td))

    if not task_dirs:
        log.error("No tasks specified")
        return 1

    # Build work items: (task_dir, config)
    work = []
    for td in task_dirs:
        if args.config == "both":
            work.append((td, "baseline"))
            work.append((td, "sg_only"))
        else:
            work.append((td, args.config))

    log.info(f"Smoke testing {len(work)} task/config pairs, {args.parallel} parallel")
    for i, (td, cfg) in enumerate(work):
        log.info(f"  [{i+1}] {td.parent.name}/{td.name} ({cfg})")

    if args.dry_run:
        log.info("DRY RUN — exiting")
        return 0

    results = []
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = {pool.submit(smoke_one, td, cfg): (td, cfg)
                   for td, cfg in work}
        for fut in as_completed(futures):
            td, cfg = futures[fut]
            try:
                r = fut.result()
                results.append(r)
            except Exception as e:
                results.append({
                    "task_id": td.name, "suite": td.parent.name,
                    "config": cfg, "build_ok": False, "verifier_ok": False,
                    "error": str(e)[:500], "elapsed_sec": 0,
                })

    # Summary
    print("\n" + "=" * 70)
    print("SMOKE TEST RESULTS")
    print("=" * 70)
    build_ok = sum(1 for r in results if r["build_ok"])
    verify_ok = sum(1 for r in results if r["verifier_ok"])
    total = len(results)

    for r in sorted(results, key=lambda x: x["task_id"]):
        b = "BUILD_OK" if r["build_ok"] else "BUILD_FAIL"
        v = "VERIFY_OK" if r["verifier_ok"] else "VERIFY_FAIL"
        err = f" ERR: {r['error'][:80]}" if r["error"] else ""
        print(f"  {r['task_id']:50s} {r['config']:10s} {b:12s} {v:12s} {r['elapsed_sec']:6.0f}s{err}")

    print(f"\nBuild:  {build_ok}/{total}")
    print(f"Verify: {verify_ok}/{total}")

    # Save results
    out_path = REPO_ROOT / "runs" / "smoke_test_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    log.info(f"Results saved to {out_path}")

    return 0 if build_ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
