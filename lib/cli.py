#!/usr/bin/env python3
"""V2 Evaluation Runner CLI.

Usage:
    run-eval run -c experiment.yaml       Run experiment
    run-eval dry-run -c experiment.yaml   Preview matrix expansion
    run-eval export -m manifest.json      Export Harbor results
    run-eval validate -c experiment.yaml  Validate configuration
    run-eval status -e experiment_id      Show experiment status
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    """Main CLI entrypoint."""
    # Load environment from <project_root>/.env.local before any validation
    # Matches v1 run_eval.sh behavior (lines 28-32)
    from lib.config.loader import load_env_file
    load_env_file()
    
    parser = argparse.ArgumentParser(
        prog="run-eval",
        description="V2 Evaluation Runner for MCP vs Baseline comparisons",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  run-eval run -c configs/minimal.yaml
  run-eval dry-run -c configs/medium_matrix.yaml
  run-eval export -m runs/exp_xxx/manifest.json
  run-eval validate -c configs/experiment.yaml
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    
    run_parser = subparsers.add_parser("run", help="Run an experiment")
    run_parser.add_argument(
        "-c", "--config",
        required=True,
        help="Path to experiment config YAML"
    )
    run_parser.add_argument(
        "--jobs-dir",
        default="runs",
        help="Harbor jobs directory (default: runs)"
    )
    run_parser.add_argument(
        "--output-dir",
        default="runs",
        help="V2 output directory (default: runs)"
    )
    run_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output"
    )
    run_parser.add_argument(
        "--force-rebuild",
        action="store_true",
        help="Force Docker environment rebuild (passes --force-build to harbor run)"
    )
    run_parser.add_argument(
        "--category",
        choices=["official", "troubleshooting", "experiment"],
        default=None,
        help="Run category for output directory routing (overrides config value)"
    )
    
    dryrun_parser = subparsers.add_parser(
        "dry-run",
        help="Preview matrix expansion without running"
    )
    dryrun_parser.add_argument(
        "-c", "--config",
        required=True,
        help="Path to experiment config YAML"
    )
    dryrun_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON"
    )
    dryrun_parser.add_argument(
        "--category",
        choices=["official", "troubleshooting", "experiment"],
        default=None,
        help="Run category for output directory routing (overrides config value)"
    )
    
    export_parser = subparsers.add_parser(
        "export",
        help="Export Harbor results to canonical format"
    )
    export_parser.add_argument(
        "-m", "--manifest",
        required=True,
        help="Path to manifest.json"
    )
    export_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing exports"
    )
    
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate experiment configuration"
    )
    validate_parser.add_argument(
        "-c", "--config",
        required=True,
        help="Path to experiment config YAML"
    )
    
    status_parser = subparsers.add_parser(
        "status",
        help="Show experiment status"
    )
    status_parser.add_argument(
        "-e", "--experiment",
        required=True,
        help="Experiment ID or path to manifest"
    )
    
    args = parser.parse_args()
    
    if args.command is None:
        parser.print_help()
        return 1
    
    try:
        if args.command == "run":
            return cmd_run(args)
        elif args.command == "dry-run":
            return cmd_dry_run(args)
        elif args.command == "export":
            return cmd_export(args)
        elif args.command == "validate":
            return cmd_validate(args)
        elif args.command == "status":
            return cmd_status(args)
        else:
            parser.print_help()
            return 1
    except KeyboardInterrupt:
        print("\n[INTERRUPTED] Execution cancelled by user")
        return 130
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1


def cmd_run(args) -> int:
    """Run an experiment."""
    from lib.config.loader import load_config, validate_config, ConfigError
    from lib.config.schema import RunCategory
    from lib.matrix.expander import MatrixExpander
    from lib.runner.executor import HarborExecutor, check_harbor_installed
    from lib.runner.pair_scheduler import PairScheduler
    from lib.runner.manifest import ManifestBuilder
    from lib.exporter.canonical import V2Exporter

    print(f"[V2 RUN] Loading config: {args.config}")

    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    if args.category:
        config.run_category = RunCategory(args.category)

    try:
        warnings = validate_config(config)
        for w in warnings:
            print(f"[WARN] {w}")
    except ConfigError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1
    
    if not check_harbor_installed():
        print("[ERROR] Harbor CLI not found. Install with: pip install harbor", file=sys.stderr)
        return 1
    
    category = config.run_category.value

    print(f"[V2 RUN] Experiment: {config.experiment_name}")
    print(f"[V2 RUN] Description: {config.description or 'N/A'}")
    print(f"[V2 RUN] Category: {category}")

    expander = MatrixExpander(config, args.config)
    runs, pairs = expander.expand()

    print(f"[V2 RUN] Matrix expanded: {len(runs)} runs, {len(pairs)} pairs")
    print(f"[V2 RUN] Experiment ID: {expander.experiment_id}")

    executor = HarborExecutor(
        jobs_dir=args.jobs_dir,
        logs_dir="logs",
        generated_dir=".generated/v2",
        force_rebuild=args.force_rebuild,
        category=category
    )
    
    def on_run_complete(scheduled):
        status = "✓" if scheduled.status.value == "completed" else "✗"
        print(f"  [{status}] {scheduled.run_spec.run_id}")
    
    scheduler = PairScheduler(
        executor=executor,
        parallel_pairs=True,
        on_run_complete=on_run_complete
    )
    
    manifest_builder = ManifestBuilder(output_root=args.output_dir, category=category)
    manifest = manifest_builder.create(
        experiment_id=expander.experiment_id,
        config=config,
        config_path=args.config,
        runs=runs,
        pairs=pairs
    )
    
    manifest.status = "running"
    manifest_builder.save_manifest(manifest)
    print(f"[V2 RUN] Manifest saved: {manifest_builder.get_experiment_dir(expander.experiment_id)}/manifest.json")
    
    print(f"[V2 RUN] Starting execution...")
    scheduled_runs, pair_executions = scheduler.schedule(runs, pairs)
    completed_runs = scheduler.execute_all(dry_run=False)
    
    exporter = V2Exporter(output_root=args.output_dir, jobs_dir=args.jobs_dir)
    exp_dir = exporter.export_experiment(manifest, completed_runs, pair_executions)
    
    summary = scheduler.get_status_summary()
    print(f"\n[V2 RUN] Complete!")
    print(f"  Runs: {summary['runs']}")
    print(f"  Pairs: {summary['pairs']}")
    print(f"  Output: {exp_dir}")
    
    return 0


def cmd_dry_run(args) -> int:
    """Preview matrix expansion without running."""
    from lib.config.loader import load_config, validate_config, ConfigError
    from lib.config.schema import RunCategory
    from lib.matrix.expander import MatrixExpander

    try:
        config = load_config(args.config)
    except ConfigError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    if args.category:
        config.run_category = RunCategory(args.category)

    try:
        warnings = validate_config(config)
    except ConfigError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    expander = MatrixExpander(config, args.config)
    runs, pairs = expander.expand()
    summary = expander.get_summary()
    
    if args.json:
        output = {
            "experiment_id": expander.experiment_id,
            "config_hash": expander.config_hash,
            "summary": summary,
            "runs": [
                {
                    "run_id": r.run_id,
                    "mcp_mode": r.mcp_mode,
                    "model": r.model,
                    "benchmark": r.benchmark,
                    "task_ids": r.task_ids,
                    "seed": r.seed,
                    "pair_id": r.pair_id,
                    "invariant_hash": r.invariant_hash,
                }
                for r in runs
            ],
            "pairs": [
                {
                    "pair_id": p.pair_id,
                    "baseline_run_id": p.baseline_run_id,
                    "mcp_run_id": p.mcp_run_id,
                    "mcp_mode": p.mcp_mode,
                    "invariant_hash": p.invariant_hash,
                }
                for p in pairs
            ],
            "warnings": warnings,
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"\n{'='*60}")
        print(f"V2 DRY RUN: {config.experiment_name}")
        print(f"{'='*60}")
        print(f"Experiment ID: {expander.experiment_id}")
        print(f"Config Hash:   {expander.config_hash[:12]}...")
        print(f"Category:      {config.run_category.value}")
        print(f"\nMatrix Dimensions:")
        for dim, count in summary["dimensions"].items():
            print(f"  {dim}: {count}")
        print(f"\nTotal Runs: {len(runs)}")
        print(f"Total Pairs: {len(pairs)}")
        
        if warnings:
            print(f"\nWarnings:")
            for w in warnings:
                print(f"  ⚠ {w}")
        
        print(f"\nRuns by MCP Mode:")
        for mode, count in summary["runs_by_mode"].items():
            print(f"  {mode}: {count}")
        
        print(f"\nRuns by Model:")
        for model, count in summary["runs_by_model"].items():
            print(f"  {model}: {count}")
        
        print(f"\nPlanned Runs:")
        for run in runs[:10]:
            pair_marker = f" [pair:{run.pair_id[:8]}...]" if run.pair_id else ""
            print(f"  {run.run_id}{pair_marker}")
        if len(runs) > 10:
            print(f"  ... and {len(runs) - 10} more")
        
        print(f"\nPlanned Pairs:")
        for pair in pairs[:5]:
            print(f"  {pair.pair_id}")
            print(f"    baseline: {pair.baseline_run_id}")
            print(f"    mcp:      {pair.mcp_run_id}")
        if len(pairs) > 5:
            print(f"  ... and {len(pairs) - 5} more")
        
        print(f"\n{'='*60}")
    
    return 0


def cmd_export(args) -> int:
    """Export Harbor results to canonical format."""
    manifest_path = Path(args.manifest)
    
    if not manifest_path.exists():
        print(f"[ERROR] Manifest not found: {manifest_path}", file=sys.stderr)
        return 1
    
    try:
        with open(manifest_path) as f:
            manifest_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON in manifest: {e}", file=sys.stderr)
        return 1
    
    exp_dir = manifest_path.parent
    experiment_id = manifest_data.get("experiment_id", exp_dir.name)
    
    print(f"[V2 EXPORT] Experiment: {experiment_id}")
    print(f"[V2 EXPORT] Re-exporting from Harbor outputs...")
    
    from lib.exporter.canonical import V2Exporter
    from lib.exporter.harbor_parser import HarborParser
    
    exporter = V2Exporter(output_root=exp_dir.parent)
    parser = HarborParser()
    
    runs_exported = 0
    for run_info in manifest_data.get("runs", []):
        run_id = run_info.get("run_id")
        if not run_id:
            continue
        
        results_path = exp_dir / "runs" / run_id / "results.json"
        if results_path.exists() and not args.force:
            print(f"  [SKIP] {run_id} (already exported, use --force to overwrite)")
            continue
        
        print(f"  [EXPORT] {run_id}")
        runs_exported += 1
    
    print(f"\n[V2 EXPORT] Exported {runs_exported} runs")
    
    return 0


def cmd_validate(args) -> int:
    """Validate experiment configuration."""
    from lib.config.loader import load_config, validate_config, ConfigError
    
    print(f"[V2 VALIDATE] Checking: {args.config}")
    
    try:
        config = load_config(args.config)
        print("[✓] YAML syntax valid")
        print("[✓] Schema validation passed")
    except ConfigError as e:
        print(f"[✗] {e}", file=sys.stderr)
        return 1
    
    try:
        warnings = validate_config(config)
        print("[✓] Runtime validation passed")
        
        if warnings:
            print("\nWarnings:")
            for w in warnings:
                print(f"  ⚠ {w}")
    except ConfigError as e:
        print(f"[✗] {e}", file=sys.stderr)
        return 1
    
    from lib.matrix.expander import MatrixExpander
    expander = MatrixExpander(config, args.config)
    runs, pairs = expander.expand()
    
    print(f"\n[✓] Configuration valid")
    print(f"    Experiment: {config.experiment_name}")
    print(f"    Runs: {len(runs)}")
    print(f"    Pairs: {len(pairs)}")
    print(f"    Estimated Experiment ID: {expander.experiment_id}")
    
    return 0


def cmd_status(args) -> int:
    """Show experiment status."""
    exp_ref = args.experiment

    if exp_ref.endswith(".json"):
        manifest_path = Path(exp_ref)
    else:
        # Search across category subdirectories, then fall back to flat runs/
        manifest_path = None
        categories = ["official", "troubleshooting", "experiment"]
        for cat in categories:
            candidate = Path("runs") / cat / exp_ref / "manifest.json"
            if candidate.exists():
                manifest_path = candidate
                break
        if manifest_path is None:
            # Fall back to legacy flat layout
            manifest_path = Path("runs") / exp_ref / "manifest.json"

    if not manifest_path.exists():
        print(f"[ERROR] Manifest not found: {manifest_path}", file=sys.stderr)
        print(f"  Searched: runs/<category>/{exp_ref}/manifest.json and runs/{exp_ref}/manifest.json", file=sys.stderr)
        return 1
    
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid JSON: {e}", file=sys.stderr)
        return 1
    
    print(f"\n{'='*60}")
    print(f"Experiment: {manifest.get('experiment_id', 'unknown')}")
    print(f"{'='*60}")
    print(f"Status:     {manifest.get('status', 'unknown')}")
    print(f"Created:    {manifest.get('created_at', 'unknown')}")
    print(f"Finished:   {manifest.get('finished_at', 'N/A')}")
    
    config = manifest.get("config", {})
    print(f"\nConfiguration:")
    print(f"  Name:        {config.get('experiment_name', 'N/A')}")
    print(f"  Benchmarks:  {', '.join(config.get('benchmarks', []))}")
    print(f"  Models:      {', '.join(config.get('models', []))}")
    print(f"  MCP Modes:   {', '.join(config.get('mcp_modes', []))}")
    
    summary = manifest.get("matrix_summary", {})
    print(f"\nMatrix Summary:")
    print(f"  Total Runs:  {summary.get('total_runs', 0)}")
    print(f"  Total Pairs: {summary.get('total_pairs', 0)}")
    
    runs = manifest.get("runs", [])
    run_statuses = {}
    for r in runs:
        status = r.get("status", "unknown")
        run_statuses[status] = run_statuses.get(status, 0) + 1
    
    print(f"\nRun Status:")
    for status, count in run_statuses.items():
        print(f"  {status}: {count}")
    
    pairs = manifest.get("pairs", [])
    pair_statuses = {}
    for p in pairs:
        status = p.get("status", "unknown")
        pair_statuses[status] = pair_statuses.get(status, 0) + 1
    
    print(f"\nPair Status:")
    for status, count in pair_statuses.items():
        print(f"  {status}: {count}")
    
    index_path = manifest_path.parent / "index.json"
    if index_path.exists():
        try:
            with open(index_path) as f:
                index = json.load(f)
            
            stats = index.get("aggregate_stats", {})
            print(f"\nAggregate Stats:")
            baseline = stats.get("baseline", {})
            mcp = stats.get("mcp", {})
            print(f"  Baseline resolution rate: {baseline.get('mean_resolution_rate', 0):.1%}")
            print(f"  MCP resolution rate:      {mcp.get('mean_resolution_rate', 0):.1%}")
            print(f"  Improvement:              {stats.get('improvement_pct', 0):+.1f}%")
        except (json.JSONDecodeError, KeyError):
            pass
    
    print(f"\n{'='*60}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
