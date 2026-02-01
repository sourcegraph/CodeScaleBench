#!/usr/bin/env python3
"""
Script to run the DI-Bench adapter and convert instances to Harbor tasks.

Usage:
    python run_adapter.py --dataset_path path/to/dataset.jsonl \
                          --repo_instances_dir path/to/repo-data \
                          --output_dir path/to/output \
                          --limit 10

Example:
    python run_adapter.py --dataset_path dibench-regular.jsonl \
                          --repo_instances_dir .cache/repo-data \
                          --output_dir ./dibench_tasks \
                          --languages python rust
"""

import argparse
import logging
from pathlib import Path

from adapter import DIBenchAdapter, DIBenchLoader

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Convert DI-Bench instances to Harbor tasks"
    )
    parser.add_argument(
        "--dataset_path",
        type=Path,
        required=True,
        help="Path to DI-Bench JSONL dataset file"
    )
    parser.add_argument(
        "--repo_instances_dir",
        type=Path,
        required=True,
        help="Directory containing extracted DI-Bench repositories"
    )
    parser.add_argument(
        "--output_dir",
        type=Path,
        required=True,
        help="Output directory for Harbor tasks"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of tasks to generate (default: all)"
    )
    parser.add_argument(
        "--languages",
        nargs="+",
        default=None,
        help="Filter by languages (e.g., python rust csharp javascript)"
    )
    parser.add_argument(
        "--instance_ids",
        nargs="+",
        default=None,
        help="Specific instance IDs to convert"
    )

    args = parser.parse_args()

    # Validate inputs
    if not args.dataset_path.exists():
        logger.error(f"Dataset file not found: {args.dataset_path}")
        return

    if not args.repo_instances_dir.exists():
        logger.error(f"Repository instances directory not found: {args.repo_instances_dir}")
        return

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize adapter
    logger.info("Initializing DI-Bench adapter...")
    adapter = DIBenchAdapter(
        task_dir=args.output_dir,
        repo_instances_dir=args.repo_instances_dir,
        dataset_path=args.dataset_path
    )

    # Get task IDs to convert
    all_task_ids = adapter.loader.all_ids()
    logger.info(f"Found {len(all_task_ids)} total instances in dataset")

    # Filter by language if specified
    if args.languages:
        languages_lower = [lang.lower() for lang in args.languages]
        task_ids = [
            tid for tid in all_task_ids
            if any(tid.startswith(f"{lang}/") for lang in languages_lower)
        ]
        logger.info(f"Filtered to {len(task_ids)} instances for languages: {args.languages}")
    else:
        task_ids = all_task_ids

    # Filter by specific instance IDs if specified
    if args.instance_ids:
        task_ids = [tid for tid in task_ids if any(iid in tid for iid in args.instance_ids)]
        logger.info(f"Filtered to {len(task_ids)} instances matching IDs: {args.instance_ids}")

    # Apply limit if specified
    if args.limit:
        task_ids = task_ids[:args.limit]
        logger.info(f"Limited to {args.limit} instances")

    # Generate tasks
    logger.info(f"Generating {len(task_ids)} Harbor tasks...")
    success_count = 0
    error_count = 0

    for i, task_id in enumerate(task_ids, 1):
        try:
            # Create local task ID from task_id (language/instance_id)
            local_id = task_id.replace("/", "-")

            logger.info(f"[{i}/{len(task_ids)}] Generating task: {task_id} -> {local_id}")
            adapter.generate_task(task_id, local_id)
            success_count += 1

        except Exception as e:
            logger.error(f"[{i}/{len(task_ids)}] Failed to generate {task_id}: {e}")
            error_count += 1

    # Summary
    logger.info("\n" + "="*60)
    logger.info(f"Task generation complete!")
    logger.info(f"  Success: {success_count}")
    logger.info(f"  Errors:  {error_count}")
    logger.info(f"  Output directory: {args.output_dir}")
    logger.info("="*60)


if __name__ == "__main__":
    main()
