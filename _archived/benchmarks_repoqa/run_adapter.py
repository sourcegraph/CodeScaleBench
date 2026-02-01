#!/usr/bin/env python3
"""
Script to run the RepoQA adapter and convert instances to Harbor tasks.

Usage:
    python run_adapter.py --dataset_path path/to/dataset.jsonl \
                          --output_dir path/to/output \
                          --variants sr-qa md-qa \
                          --limit 10

Example:
    python run_adapter.py --dataset_path repoqa-instances.jsonl \
                          --output_dir ./repoqa_tasks \
                          --languages python javascript \
                          --variants sr-qa \
                          --limit 5
"""

import argparse
import logging
from pathlib import Path

from adapter import RepoQAAdapter, RepoQALoader
from commit_validator import validate_dataset, print_validation_report

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Convert RepoQA instances to Harbor tasks"
    )
    parser.add_argument(
        "--dataset_path",
        type=Path,
        required=True,
        help="Path to RepoQA JSONL dataset file"
    )
    parser.add_argument(
        "--output_dir",
        type=Path,
        required=True,
        help="Output directory for Harbor tasks"
    )
    parser.add_argument(
        "--variants",
        nargs="+",
        default=["sr-qa"],
        choices=["sr-qa", "md-qa", "nr-qa"],
        help="Task variants to generate (default: sr-qa)"
    )
    parser.add_argument(
        "--languages",
        nargs="+",
        default=None,
        help="Filter by languages (e.g., python javascript rust)"
    )
    parser.add_argument(
        "--instance_ids",
        nargs="+",
        default=None,
        help="Specific instance IDs to convert"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of tasks to generate per variant (default: all)"
    )
    parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip commit hash validation (faster, but may generate invalid tasks)"
    )

    args = parser.parse_args()

    # Validate inputs
    if not args.dataset_path.exists():
        logger.error(f"Dataset file not found: {args.dataset_path}")
        return
    
    # Validate commit hashes
    if not args.skip_validation:
        logger.info("Validating commit hashes in dataset...")
        validation_results = validate_dataset(args.dataset_path)
        all_valid = print_validation_report(validation_results)
        if not all_valid:
            logger.error("❌ Dataset validation failed. Some commits are invalid.")
            logger.error("   Fix the dataset or use --skip-validation to proceed anyway")
            return

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize adapter
    logger.info("Initializing RepoQA adapter...")
    adapter = RepoQAAdapter(
        task_dir=args.output_dir,
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
            if adapter.loader.load(tid).language.lower() in languages_lower
        ]
        logger.info(f"Filtered to {len(task_ids)} instances for languages: {args.languages}")
    else:
        task_ids = all_task_ids

    # Filter by specific instance IDs if specified
    if args.instance_ids:
        task_ids = [tid for tid in task_ids if tid in args.instance_ids]
        logger.info(f"Filtered to {len(task_ids)} instances matching IDs: {args.instance_ids}")

    # Apply limit if specified
    if args.limit:
        task_ids = task_ids[:args.limit]
        logger.info(f"Limited to {args.limit} instances")

    # Generate tasks for each variant
    total_tasks = len(task_ids) * len(args.variants)
    task_count = 0
    success_count = 0
    error_count = 0

    for variant in args.variants:
        logger.info(f"\nGenerating {len(task_ids)} tasks for variant: {variant}")
        
        for i, task_id in enumerate(task_ids, 1):
            task_count += 1
            try:
                # Create local task ID: instance-id-variant
                local_id = f"{task_id}-{variant}"

                logger.info(f"[{task_count}/{total_tasks}] Generating {local_id}")
                adapter.generate_task(task_id, local_id, task_variant=variant)
                success_count += 1

            except Exception as e:
                logger.error(f"[{task_count}/{total_tasks}] Failed to generate {task_id}: {e}")
                error_count += 1

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info(f"Task generation complete!")
    logger.info(f"  Variants: {', '.join(args.variants)}")
    logger.info(f"  Success: {success_count}/{total_tasks}")
    logger.info(f"  Errors:  {error_count}/{total_tasks}")
    logger.info(f"  Output directory: {args.output_dir}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
