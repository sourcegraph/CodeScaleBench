#!/usr/bin/env python3
"""
CLI for generating Harbor tasks from PRDBench.

Reads PRDBench tasks and generates Harbor task directories using
the PRDBenchAdapter.

Usage:
    python run_adapter.py --output_dir ./tasks/
    python run_adapter.py --output_dir ./tasks/ --task_ids task-001 task-002
    python run_adapter.py --output_dir ./tasks/ --limit 10
"""

import argparse
import logging
import sys
from pathlib import Path

from adapter import PRDBenchAdapter, PRDBenchLoader

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main(
    output_dir: Path,
    data_dir: Path | None = None,
    task_ids: list[str] | None = None,
    limit: int | None = None,
) -> int:
    """
    Generate Harbor tasks from PRDBench.

    Args:
        output_dir: Output directory for generated tasks.
        data_dir: Optional path to PRDBench data directory.
        task_ids: Optional list of specific task IDs to generate.
        limit: Optional limit on number of tasks to generate.

    Returns:
        Exit code (0 for success, 1 for errors).
    """
    # Initialize loader
    logger.info("Loading PRDBench tasks...")
    loader = PRDBenchLoader(data_dir)
    all_tasks = loader.load()
    logger.info(f"Found {len(all_tasks)} tasks total")

    # Filter by task_ids if specified
    if task_ids:
        logger.info(f"Filtering to specified task IDs: {task_ids}")
        tasks = [t for t in all_tasks if t.id in task_ids]

        # Warn about missing tasks
        found_ids = {t.id for t in tasks}
        missing_ids = set(task_ids) - found_ids
        if missing_ids:
            logger.warning(f"Task IDs not found: {missing_ids}")

        logger.info(f"After filtering: {len(tasks)} tasks")
    else:
        tasks = all_tasks

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
    adapter = PRDBenchAdapter(
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
        description="Generate Harbor tasks from PRDBench",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Generate all tasks
    python run_adapter.py --output_dir ./tasks/

    # Generate specific tasks by ID
    python run_adapter.py --output_dir ./tasks/ --task_ids task-001 task-002 task-003

    # Generate first 10 tasks
    python run_adapter.py --output_dir ./tasks/ --limit 10

    # Combine options
    python run_adapter.py --output_dir ./tasks/ --task_ids task-001 task-002 --limit 1
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
        help="Path to PRDBench data directory (default: benchmarks/prdbench/data/)",
    )

    parser.add_argument(
        "--task_ids",
        type=str,
        nargs="+",
        help="Specific task IDs to generate (space-separated)",
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
        task_ids=args.task_ids,
        limit=args.limit,
    )
    sys.exit(exit_code)
