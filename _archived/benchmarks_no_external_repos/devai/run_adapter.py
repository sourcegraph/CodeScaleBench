#!/usr/bin/env python3
"""
CLI for generating Harbor tasks from DevAI.

Reads DevAI tasks and generates Harbor task directories using
the DevAIAdapter.

Usage:
    python run_adapter.py --output_dir ./tasks/
    python run_adapter.py --output_dir ./tasks/ --domain web
    python run_adapter.py --output_dir ./tasks/ --limit 10
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from adapter import DevAIAdapter, DevAILoader, DEVAI_DOMAINS

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
    domain: Optional[str] = None,
    limit: Optional[int] = None,
) -> int:
    """
    Generate Harbor tasks from DevAI.

    Args:
        output_dir: Output directory for generated tasks.
        data_dir: Optional path to DevAI data directory.
        domain: Optional domain to filter by.
        limit: Optional limit on number of tasks to generate.

    Returns:
        Exit code (0 for success, 1 for errors).
    """
    # Initialize loader
    logger.info("Loading DevAI tasks...")
    loader = DevAILoader(data_dir)
    tasks = loader.load()
    logger.info(f"Found {len(tasks)} tasks total")

    # Apply filters
    if domain:
        logger.info(f"Filtering by domain: {domain}")
        tasks = loader.filter_by_domain(domain)
        logger.info(f"After domain filter: {len(tasks)} tasks")

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
    adapter = DevAIAdapter(
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
        description="Generate Harbor tasks from DevAI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Generate all tasks
    python run_adapter.py --output_dir ./tasks/

    # Generate tasks from specific domain
    python run_adapter.py --output_dir ./tasks/ --domain web

    # Generate first 10 tasks
    python run_adapter.py --output_dir ./tasks/ --limit 10

    # Combine filters
    python run_adapter.py --output_dir ./tasks/ --domain cli --limit 5
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
        help="Path to DevAI data directory (default: benchmarks/devai/data/)",
    )

    parser.add_argument(
        "--domain",
        type=str,
        choices=DEVAI_DOMAINS,
        help="Filter by domain (web, cli, data, automation, api, ml, testing, devops)",
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
        domain=args.domain,
        limit=args.limit,
    )
    sys.exit(exit_code)
