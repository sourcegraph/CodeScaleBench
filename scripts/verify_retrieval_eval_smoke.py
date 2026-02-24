#!/usr/bin/env python3
"""One-command smoke verification for the retrieval evaluation framework.

Runs a small set of end-to-end checks over existing staging runs:
1. Small single-run pipeline (write-event/utilization probe sanity)
2. Single-run matched-comparison case (impact analysis computable)
3. Pooled multi-run case (pooled matched-comparison report formatting)

Outputs are written under tmp/ and assertions fail fast on regressions.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


DEFAULT_FIX_RUN = "ccb_fix_haiku_20260223_024435"
DEFAULT_DEBUG_RUN = "ccb_debug_haiku_20260222_195334"
DEFAULT_POOLED_RUNS = [
    "ccb_debug_haiku_20260222_195334",
    "ccb_mcp_crossrepo_tracing_haiku_20260221_140913",
    "ccb_mcp_onboarding_haiku_20260221_140913",
]


def _run(cmd: list[str], cwd: Path) -> None:
    print(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _symlink_run_subset(staging_root: Path, names: list[str], dest_root: Path) -> None:
    runs_dir = dest_root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        src = staging_root / name
        _assert(src.is_dir(), f"Required run missing: {src}")
        dst = runs_dir / name
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(src)


def _find_one(path_glob: str) -> Path:
    matches = sorted(REPO_ROOT.glob(path_glob))
    _assert(bool(matches), f"No files matched: {path_glob}")
    return matches[0]


def verify_small_fix_run(staging_root: Path, out_root: Path) -> dict:
    run_dir = staging_root / DEFAULT_FIX_RUN
    _assert(run_dir.is_dir(), f"Missing fix run: {run_dir}")
    out = out_root / "single_fix"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)

    _run(["python3", "scripts/normalize_retrieval_events.py", "--run-dir", str(run_dir)], REPO_ROOT)
    with (out / "normalize.log").open("w") as f:
        subprocess.run(
            ["python3", "scripts/retrieval_eval_pipeline.py", "--run-dir", str(run_dir), "--output-dir", str(out / "artifacts")],
            cwd=REPO_ROOT,
            check=True,
            stdout=f,
        )
    _run(
        [
            "python3", "scripts/retrieval_impact_analysis.py",
            "--run-dir", str(run_dir),
            "--events-dir", str(out / "artifacts"),
            "-o", str(out / "impact.json"),
        ],
        REPO_ROOT,
    )
    _run(
        [
            "python3", "scripts/generate_retrieval_report.py",
            "--summary", str(out / "artifacts" / "run_retrieval_summary.json"),
            "--impact", str(out / "impact.json"),
            "-o", str(out / "report.md"),
        ],
        REPO_ROOT,
    )

    artifact = _find_one(str((out / "artifacts" / "baseline-local-direct" / "*.retrieval_metrics.json").relative_to(REPO_ROOT)))
    a = _load_json(artifact)
    util = a.get("utilization_probes", {})
    _assert(util.get("probe_available") is True, "Expected utilization probe_available=true in small fix run")
    _assert(
        util.get("util_read_overlap_with_relevant_files") is not None,
        "Expected read-overlap utilization metric in small fix run",
    )

    norm_event = _find_one(
        f"runs/staging/{DEFAULT_FIX_RUN}/retrieval_events/baseline-local-direct/*.retrieval_events.json"
    )
    events_doc = _load_json(norm_event)
    cats: dict[str, int] = {}
    for evt in events_doc.get("events", []):
        cats[evt.get("tool_category", "unknown")] = cats.get(evt.get("tool_category", "unknown"), 0) + 1
    _assert(cats.get("file_write", 0) > 0, "Expected file_write events in normalized events")

    run_summary = _load_json(out / "artifacts" / "run_retrieval_summary.json")
    file_agg = run_summary.get("file_level_aggregates", {})

    return {
        "run": DEFAULT_FIX_RUN,
        "total_event_files": run_summary.get("total_event_files"),
        "computable_tasks": run_summary.get("computable_tasks"),
        "mean_file_recall": file_agg.get("file_recall", {}).get("mean"),
        "mean_mrr": file_agg.get("mrr", {}).get("mean"),
        "util_probe_available": util.get("probe_available"),
        "util_read_overlap_with_relevant_files": util.get("util_read_overlap_with_relevant_files"),
        "util_write_overlap_with_relevant_files_proxy": util.get("util_write_overlap_with_relevant_files_proxy"),
        "util_write_overlap_with_expected_edit_files": util.get("util_write_overlap_with_expected_edit_files"),
        "util_read_before_write_ratio": util.get("util_read_before_write_ratio"),
        "event_categories": cats,
    }


def verify_debug_matched_run(staging_root: Path, out_root: Path) -> dict:
    run_dir = staging_root / DEFAULT_DEBUG_RUN
    _assert(run_dir.is_dir(), f"Missing debug run: {run_dir}")
    out = out_root / "single_debug"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)

    _run(["python3", "scripts/normalize_retrieval_events.py", "--run-dir", str(run_dir)], REPO_ROOT)
    with (out / "pipeline_summary.json").open("w") as f:
        subprocess.run(
            ["python3", "scripts/retrieval_eval_pipeline.py", "--run-dir", str(run_dir), "--output-dir", str(out / "artifacts")],
            cwd=REPO_ROOT,
            check=True,
            stdout=f,
        )
    _run(
        [
            "python3", "scripts/retrieval_impact_analysis.py",
            "--run-dir", str(run_dir),
            "--events-dir", str(out / "artifacts"),
            "-o", str(out / "impact.json"),
        ],
        REPO_ROOT,
    )
    _run(
        [
            "python3", "scripts/generate_retrieval_report.py",
            "--summary", str(out / "artifacts" / "run_retrieval_summary.json"),
            "--impact", str(out / "impact.json"),
            "-o", str(out / "report.md"),
        ],
        REPO_ROOT,
    )

    impact = _load_json(out / "impact.json")
    mc = impact.get("matched_comparison", {})
    corr = impact.get("correlation_analysis", {})
    _assert(mc.get("computable") is True, "Expected matched_comparison.computable=true for debug run")
    _assert((mc.get("n_matched_tasks") or 0) >= 3, "Expected >=3 matched tasks for debug run")

    return {
        "run": DEFAULT_DEBUG_RUN,
        "correlation_computable": corr.get("computable"),
        "correlation_n_joined": corr.get("n_joined"),
        "correlation_pairs": len(corr.get("correlations", [])) if corr.get("computable") else 0,
        "matched_computable": mc.get("computable"),
        "matched_tasks": mc.get("n_matched_tasks"),
        "runs_compared": mc.get("n_runs_compared", 1),
        "baseline_config": mc.get("baseline_config"),
        "mcp_config": mc.get("mcp_config"),
    }


def verify_pooled_multi_run(staging_root: Path, out_root: Path) -> dict:
    out = out_root / "pooled_multi"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)
    _symlink_run_subset(staging_root, DEFAULT_POOLED_RUNS, out)

    pooled_runs_root = out / "runs"
    _run(["python3", "scripts/normalize_retrieval_events.py", "--run-dir", str(pooled_runs_root), "--all"], REPO_ROOT)
    (out / "out").mkdir(parents=True, exist_ok=True)
    with (out / "pipeline_summary.json").open("w") as f:
        subprocess.run(
            [
                "python3", "scripts/retrieval_eval_pipeline.py",
                "--run-dir", str(pooled_runs_root),
                "--all",
                "--output-dir", str(out / "out"),
            ],
            cwd=REPO_ROOT,
            check=True,
            stdout=f,
        )
    _run(
        [
            "python3", "scripts/retrieval_impact_analysis.py",
            "--run-dir", str(pooled_runs_root),
            "--all",
            "--events-dir", str(out / "out"),
            "-o", str(out / "impact.json"),
        ],
        REPO_ROOT,
    )
    _run(
        [
            "python3", "scripts/generate_retrieval_report.py",
            "--summary", str(out / "out" / "run_retrieval_summary.json"),
            "--impact", str(out / "impact.json"),
            "-o", str(out / "report.md"),
        ],
        REPO_ROOT,
    )

    impact = _load_json(out / "impact.json")
    mc = impact.get("matched_comparison", {})
    _assert(mc.get("computable") is True, "Expected pooled matched comparison to be computable")
    _assert((mc.get("n_runs_compared") or 0) >= 2, "Expected pooled run to compare >=2 runs")
    report_text = (out / "report.md").read_text()
    _assert("Pooled paired comparison" in report_text, "Expected pooled matched-comparison report header")
    _assert("- Runs compared:" in report_text, "Expected pooled report run-count details")

    return {
        "runs": DEFAULT_POOLED_RUNS,
        "matched_computable": mc.get("computable"),
        "matched_tasks": mc.get("n_matched_tasks"),
        "n_runs_compared": mc.get("n_runs_compared"),
        "n_runs_skipped": mc.get("n_runs_skipped"),
        "baseline_configs": mc.get("baseline_configs"),
        "mcp_configs": mc.get("mcp_configs"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one-command smoke verification for retrieval evaluation framework.",
    )
    parser.add_argument(
        "--staging-root",
        type=Path,
        default=REPO_ROOT / "runs" / "staging",
        help="Path to staging runs root (default: runs/staging).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "tmp" / "retrieval_eval_verification",
        help="Directory for smoke outputs and generated reports.",
    )
    args = parser.parse_args()

    staging_root = args.staging_root.resolve()
    out_root = args.output_root.resolve()
    _assert(staging_root.is_dir(), f"staging root not found: {staging_root}")
    out_root.mkdir(parents=True, exist_ok=True)

    results = {
        "single_fix": verify_small_fix_run(staging_root, out_root),
        "single_debug": verify_debug_matched_run(staging_root, out_root),
        "pooled_multi": verify_pooled_multi_run(staging_root, out_root),
    }

    summary_path = out_root / "verification_summary.json"
    summary_path.write_text(json.dumps(results, indent=2) + "\n")

    print("\nVerification summary:")
    print(json.dumps(results, indent=2))
    print(f"\nWrote summary to {summary_path}")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
