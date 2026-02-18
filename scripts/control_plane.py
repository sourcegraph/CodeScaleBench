#!/usr/bin/env python3
"""Deterministic control plane: generate run manifest from spec + task source.

Same spec + same task source → same experiment_id, run_ids, pair_ids, and ordering.
See docs/CONTROL_PLANE.md for design and usage.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Repo root = parent of scripts/
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml
from lib.config.loader import get_config_hash
from lib.matrix.id_generator import (
    generate_experiment_id,
    generate_run_id,
    generate_pair_id,
)


def load_spec(spec_path: Path) -> dict:
    """Load control plane spec YAML."""
    with open(spec_path) as f:
        data = yaml.safe_load(f)
    if not data or "experiment_name" not in data:
        raise ValueError(f"Invalid control plane spec: {spec_path}")
    return data


def load_tasks(task_source_path: Path, benchmark_filter: str) -> list[dict]:
    """Load tasks from JSON; filter by benchmark; return sorted list."""
    with open(task_source_path) as f:
        data = json.load(f)
    tasks = data.get("tasks") or []
    if benchmark_filter:
        tasks = [t for t in tasks if t.get("benchmark") == benchmark_filter]
    # Deterministic order: benchmark then task_id
    tasks.sort(key=lambda t: (t.get("benchmark", ""), t.get("task_id", "")))
    return tasks


def build_manifest(spec_path: Path, spec: dict, repo_root: Path) -> dict:
    """Build manifest from spec and task source (deterministic)."""
    task_source = spec.get("task_source") or "configs/selected_benchmark_tasks.json"
    task_source_path = (repo_root / task_source).resolve()
    if not task_source_path.exists():
        raise FileNotFoundError(f"Task source not found: {task_source_path}")

    tasks = load_tasks(task_source_path, (spec.get("benchmark_filter") or "").strip())
    if not tasks:
        raise ValueError("No tasks after filtering")

    config_hash = get_config_hash(spec_path)
    experiment_name = spec["experiment_name"]
    # Use a fixed date (today) so same-day re-runs get same experiment_id
    timestamp = datetime.utcnow().isoformat()
    experiment_id = generate_experiment_id(experiment_name, config_hash, timestamp=timestamp)

    models = spec.get("models") or ["anthropic/claude-opus-4-6"]
    mcp_modes = spec.get("mcp_modes") or ["baseline", "sourcegraph_full"]
    seeds = spec.get("seeds") or [0]
    run_category = spec.get("run_category") or "staging"

    runs: list[dict] = []
    run_id_by_key: dict[tuple, str] = {}

    for task in tasks:
        task_id = task.get("task_id") or ""
        task_dir = task.get("task_dir") or ""
        benchmark = task.get("benchmark") or ""
        for model in models:
            for seed in seeds:
                for mcp_mode in mcp_modes:
                    run_id = generate_run_id(
                        mcp_mode=mcp_mode,
                        model=model,
                        task_id=task_id,
                        seed=seed,
                        experiment_id=experiment_id,
                    )
                    run_id_by_key[(task_id, model, seed, mcp_mode)] = run_id
                    runs.append({
                        "run_id": run_id,
                        "task_id": task_id,
                        "task_dir": task_dir,
                        "benchmark": benchmark,
                        "mcp_mode": mcp_mode,
                        "model": model,
                        "seed": seed,
                    })

    # Build pairs (baseline + sourcegraph_full per task/model/seed)
    baseline_mode = "baseline"
    pairs: list[dict] = []
    for task in tasks:
        task_id = task.get("task_id") or ""
        for model in models:
            for seed in seeds:
                base_run_id = run_id_by_key.get((task_id, model, seed, baseline_mode))
                if not base_run_id:
                    continue
                for mcp_mode in mcp_modes:
                    if mcp_mode == baseline_mode:
                        continue
                    mcp_run_id = run_id_by_key.get((task_id, model, seed, mcp_mode))
                    if not mcp_run_id:
                        continue
                    pair_id = generate_pair_id(base_run_id, mcp_run_id)
                    pairs.append({
                        "pair_id": pair_id,
                        "baseline_run_id": base_run_id,
                        "mcp_run_id": mcp_run_id,
                        "mcp_mode": mcp_mode,
                        "task_id": task_id,
                        "benchmark": task.get("benchmark") or "",
                        "model": model,
                        "seed": seed,
                    })

    # Attach pair_id to each run for convenience
    pair_id_by_baseline: dict[str, str] = {}
    pair_id_by_mcp: dict[str, str] = {}
    for p in pairs:
        pair_id_by_baseline[p["baseline_run_id"]] = p["pair_id"]
        pair_id_by_mcp[p["mcp_run_id"]] = p["pair_id"]
    for r in runs:
        r["pair_id"] = pair_id_by_baseline.get(r["run_id"]) or pair_id_by_mcp.get(r["run_id"]) or ""

    generated_at = datetime.utcnow().isoformat() + "Z"
    return {
        "experiment_id": experiment_id,
        "experiment_name": experiment_name,
        "run_category": run_category,
        "description": spec.get("description") or "",
        "generated_at": generated_at,
        "task_source": str(task_source_path),
        "spec_path": str(spec_path),
        "runs": runs,
        "pairs": pairs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic control plane: generate run manifest from spec + task source."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="Generate manifest from spec")
    gen.add_argument("--spec", required=True, help="Path to control plane spec YAML")
    gen.add_argument(
        "--output",
        help="Output path for manifest JSON (default: print to stdout)",
    )
    gen.add_argument(
        "--dry-run",
        action="store_true",
        help="Print summary only, do not write manifest",
    )
    gen.add_argument(
        "--repo-root",
        default=REPO_ROOT,
        type=Path,
        help="Repo root (default: parent of scripts/)",
    )
    args = parser.parse_args()

    if args.command != "generate":
        return 0

    spec_path = Path(args.spec)
    if not spec_path.is_absolute():
        spec_path = (args.repo_root / spec_path).resolve()
    if not spec_path.exists():
        print(f"ERROR: Spec not found: {spec_path}", file=sys.stderr)
        return 1

    try:
        spec = load_spec(spec_path)
        manifest = build_manifest(spec_path, spec, Path(args.repo_root))
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"Experiment: {manifest['experiment_name']}")
        print(f"Experiment ID: {manifest['experiment_id']}")
        print(f"Run category: {manifest['run_category']}")
        print(f"Total runs: {len(manifest['runs'])}")
        print(f"Total pairs: {len(manifest['pairs'])}")
        print("\nFirst 5 runs:")
        for r in manifest["runs"][:5]:
            print(f"  {r['run_id']}  {r['benchmark']}/{r['task_id']}  {r['mcp_mode']}")
        return 0

    out_path = args.output
    if out_path:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(manifest, f, indent=2)
        print(f"Wrote manifest: {out_path}")
    else:
        print(json.dumps(manifest, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
