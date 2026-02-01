#!/usr/bin/env python3
"""
CLI for generating Harbor tasks from LoCoBench-Agent scenarios.

Reads LoCoBench tasks from a JSONL dataset file and generates Harbor task
directories using the LoCoBenchAdapter.

Usage:
    python run_adapter.py --dataset_path locobench_dataset.jsonl --output_dir ./tasks/
    python run_adapter.py --dataset_path locobench_dataset.jsonl --output_dir ./tasks/ --task_ids id1 id2 id3
    python run_adapter.py --dataset_path locobench_dataset.jsonl --output_dir ./tasks/ --limit 10
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional

from adapter import LoCoBenchAdapter, LoCoBenchLoader

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_task_ids_from_selected(selected_tasks_path: Path) -> List[str]:
    """Load task IDs from a selected_tasks.json file.

    Args:
        selected_tasks_path: Path to selected_tasks.json

    Returns:
        List of task IDs
    """
    with open(selected_tasks_path, "r") as f:
        data = json.load(f)
    return [task["id"] for task in data.get("tasks", [])]


def main(
    dataset_path: Path,
    output_dir: Path,
    task_ids: Optional[List[str]] = None,
    limit: Optional[int] = None,
    data_dir: Optional[Path] = None,
) -> int:
    """
    Generate Harbor tasks from LoCoBench-Agent scenarios.

    Args:
        dataset_path: Path to JSONL dataset file
        output_dir: Output directory for generated tasks
        task_ids: Optional list of specific task IDs to generate
        limit: Optional limit on number of tasks to generate
        data_dir: Optional path to LoCoBench data directory

    Returns:
        Exit code (0 for success, 1 for errors)
    """
    # Validate dataset path
    if not dataset_path.exists():
        logger.error(f"Dataset file not found: {dataset_path}")
        return 1

    # Initialize loader and get task IDs
    logger.info(f"Loading tasks from {dataset_path}")
    loader = LoCoBenchLoader(dataset_path=dataset_path, data_dir=data_dir)
    all_task_ids = loader.all_ids()
    logger.info(f"Found {len(all_task_ids)} tasks in dataset")

    # Determine which tasks to generate
    if task_ids:
        # Validate provided task IDs
        invalid_ids = [tid for tid in task_ids if tid not in all_task_ids]
        if invalid_ids:
            logger.warning(f"Skipping invalid task IDs: {invalid_ids}")
        tasks_to_generate = [tid for tid in task_ids if tid in all_task_ids]
    else:
        tasks_to_generate = all_task_ids

    # Apply limit if specified
    if limit is not None and limit > 0:
        tasks_to_generate = tasks_to_generate[:limit]

    if not tasks_to_generate:
        logger.error("No valid tasks to generate")
        return 1

    logger.info(f"Generating {len(tasks_to_generate)} tasks to {output_dir}")

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize adapter
    adapter = LoCoBenchAdapter(
        task_dir=output_dir,
        data_dir=data_dir,
        dataset_path=dataset_path,
    )

    # Generate tasks with progress logging
    success_count = 0
    error_count = 0
    errors: List[tuple] = []

    for i, task_id in enumerate(tasks_to_generate, 1):
        progress = f"[{i}/{len(tasks_to_generate)}]"
        try:
            logger.info(f"{progress} Generating task: {task_id}")
            # Use task_id as the local directory name
            adapter.generate_task(task_id, task_id)
            success_count += 1
        except Exception as e:
            error_count += 1
            errors.append((task_id, str(e)))
            logger.error(f"{progress} Error generating {task_id}: {e}")
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
        description="Generate Harbor tasks from LoCoBench-Agent scenarios",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Generate all tasks from dataset
    python run_adapter.py --dataset_path locobench_dataset.jsonl --output_dir ./tasks/

    # Generate specific tasks
    python run_adapter.py --dataset_path locobench_dataset.jsonl --output_dir ./tasks/ \\
        --task_ids python_api_001_bug_investigation_hard_01 rust_web_002_security_analysis_expert_01

    # Generate first 10 tasks
    python run_adapter.py --dataset_path locobench_dataset.jsonl --output_dir ./tasks/ --limit 10

    # Use selected_tasks.json for task IDs
    python run_adapter.py --dataset_path locobench_dataset.jsonl --output_dir ./tasks/ \\
        --selected_tasks selected_tasks.json
        """,
    )

    parser.add_argument(
        "--dataset_path",
        type=Path,
        required=True,
        help="Path to JSONL dataset file (from extract_dataset.py)",
    )

    parser.add_argument(
        "--output_dir",
        type=Path,
        required=True,
        help="Output directory for generated Harbor tasks",
    )

    parser.add_argument(
        "--task_ids",
        type=str,
        nargs="*",
        help="Specific task IDs to generate (space-separated)",
    )

    parser.add_argument(
        "--selected_tasks",
        type=Path,
        help="Path to selected_tasks.json to load task IDs from",
    )

    parser.add_argument(
        "--limit",
        type=int,
        help="Maximum number of tasks to generate",
    )

    parser.add_argument(
        "--data_dir",
        type=Path,
        help="Path to LoCoBench data directory (default: benchmarks/locobench_agent/data/)",
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    # Load task IDs from selected_tasks.json if provided
    task_ids = args.task_ids
    if args.selected_tasks:
        if not args.selected_tasks.exists():
            logger.error(f"Selected tasks file not found: {args.selected_tasks}")
            sys.exit(1)
        task_ids = load_task_ids_from_selected(args.selected_tasks)
        logger.info(f"Loaded {len(task_ids)} task IDs from {args.selected_tasks}")

    exit_code = main(
        dataset_path=args.dataset_path,
        output_dir=args.output_dir,
        task_ids=task_ids,
        limit=args.limit,
        data_dir=args.data_dir,
    )
    sys.exit(exit_code)
