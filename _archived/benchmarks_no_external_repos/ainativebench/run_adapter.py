#!/usr/bin/env python3
"""
CLI for generating Harbor tasks from AINativeBench.

Reads AINativeBench tasks and generates Harbor task directories using
the AINativeBenchAdapter.

Usage:
    python run_adapter.py --output_dir ./tasks/
    python run_adapter.py --output_dir ./tasks/ --benchmark repobench --variant easy
    python run_adapter.py --output_dir ./tasks/ --limit 10
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from adapter import AINativeBenchAdapter, AINativeBenchLoader

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main(
    output_dir: Path,
    data_dir: Optional[Path] = None,
    benchmark: Optional[str] = None,
    variant: Optional[str] = None,
    limit: Optional[int] = None,
) -> int:
    """
    Generate Harbor tasks from AINativeBench.

    Args:
        output_dir: Output directory for generated tasks.
        data_dir: Optional path to AINativeBench data directory.
        benchmark: Optional benchmark name to filter by.
        variant: Optional variant to filter by.
        limit: Optional limit on number of tasks to generate.

    Returns:
        Exit code (0 for success, 1 for errors).
    """
    # Initialize loader
    logger.info("Loading AINativeBench tasks...")
    loader = AINativeBenchLoader(data_dir)
    tasks = loader.load()
    logger.info(f"Found {len(tasks)} tasks total")

    # Apply filters
    if benchmark:
        logger.info(f"Filtering by benchmark: {benchmark}")
        tasks = loader.filter_by_benchmark(benchmark)
        logger.info(f"After benchmark filter: {len(tasks)} tasks")

    if variant:
        logger.info(f"Filtering by variant: {variant}")
        if benchmark:
            # Already filtered by benchmark, now filter by variant
            tasks = [t for t in tasks if t.variant.lower() == variant.lower()]
        else:
            tasks = loader.filter_by_variant(variant)
        logger.info(f"After variant filter: {len(tasks)} tasks")

    # Apply limit
    if limit is not None and limit > 0:
        tasks = tasks[:limit]
        logger.info(f"Limited to {len(tasks)} tasks")

    if not tasks:
        logger.error("No tasks to generate after applying filters")
        return 1

    logger.info(f"Generating {len(tasks)} tasks to {output_dir}")

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize adapter
    adapter = AINativeBenchAdapter(
        task_dir=output_dir,
        data_dir=data_dir,
    )

    # Generate tasks with progress logging
    success_count = 0
    error_count = 0
    errors: list[tuple[str, str]] = []

    for i, task in enumerate(tasks, 1):
        progress = f"[{i}/{len(tasks)}]"
        try:
            logger.info(f"{progress} Generating task: {task.id}")
            adapter.generate_task(task.id)
            success_count += 1
        except Exception as e:
            error_count += 1
            errors.append((task.id, str(e)))
            logger.error(f"{progress} Error generating {task.id}: {e}")
            # Continue with next task - don't stop on error

    # Summary
    logger.info(f"Generation complete: {success_count} succeeded, {error_count} failed")

    if errors:
        logger.warning("Failed tasks:")
        for task_id, error in errors:
            logger.warning(f"  - {task_id}: {error}")

    return 0 if error_count == 0 else 1


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate Harbor tasks from AINativeBench",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Generate all tasks
    python run_adapter.py --output_dir ./tasks/

    # Generate tasks from specific benchmark
    python run_adapter.py --output_dir ./tasks/ --benchmark repobench

    # Generate tasks from specific benchmark and variant
    python run_adapter.py --output_dir ./tasks/ --benchmark repobench --variant easy

    # Generate first 10 tasks
    python run_adapter.py --output_dir ./tasks/ --limit 10

    # Combine filters
    python run_adapter.py --output_dir ./tasks/ --benchmark swe-bench --variant hard --limit 5
        """,
    )

    parser.add_argument(
        "--output_dir",
        type=Path,
        required=True,
        help="Output directory for generated Harbor tasks",
    )

    parser.add_argument(
        "--data_dir",
        type=Path,
        help="Path to AINativeBench data directory (default: benchmarks/ainativebench/data/)",
    )

    parser.add_argument(
        "--benchmark",
        type=str,
        choices=[
            "repobench",
            "crosscodeeval",
            "repoexec",
            "swe-bench",
            "devbench",
            "cocomic",
            "evocodebench",
            "mdeval",
        ],
        help="Filter by benchmark name",
    )

    parser.add_argument(
        "--variant",
        type=str,
        choices=["easy", "medium", "hard", "retrieval"],
        help="Filter by variant",
    )

    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of tasks to generate",
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    exit_code = main(
        output_dir=args.output_dir,
        data_dir=args.data_dir,
        benchmark=args.benchmark,
        variant=args.variant,
        limit=args.limit,
    )
    sys.exit(exit_code)
