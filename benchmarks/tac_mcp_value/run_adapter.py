#!/usr/bin/env python3
"""
TAC (TheAgentCompany) Adapter CLI.

Generates Harbor-compatible tasks from TheAgentCompany benchmark tasks.
TAC tasks run in pre-built Docker images with built-in checkpoint evaluation.

Usage:
    python run_adapter.py --output_dir /path/to/output
    python run_adapter.py --role SWE --limit 5 --output_dir /tmp/tac_tasks
    python run_adapter.py --task tac-implement-hyperloglog --output_dir /tmp/tac_tasks
    python run_adapter.py --list
    python run_adapter.py --stats

Examples:
    # Generate all TAC tasks
    python run_adapter.py --output_dir ./output

    # Generate only SWE (Software Engineering) tasks
    python run_adapter.py --role SWE --output_dir ./output

    # Generate first 3 tasks
    python run_adapter.py --limit 3 --output_dir ./output

    # Generate a specific task
    python run_adapter.py --task tac-implement-hyperloglog --output_dir ./output

    # List available tasks
    python run_adapter.py --list

    # Show statistics
    python run_adapter.py --stats
"""

import argparse
import sys
from pathlib import Path

# Add parent directories to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from benchmarks.tac_mcp_value.adapter import TACAdapter, TACLoader, TAC_ROLES


def list_tasks(loader: TACLoader) -> None:
    """Print list of available tasks."""
    tasks = loader.load()

    print("\nAvailable TAC Tasks")
    print("=" * 90)
    print(f"{'Harbor ID':<30} {'Role':<8} {'Difficulty':<10} {'MCP Value':<12} {'Grading':<14}")
    print("-" * 90)

    for task in tasks:
        print(
            f"{task.id:<30} {task.role:<8} {task.difficulty:<10} "
            f"{task.mcp_value:<12} {task.grading_type:<14}"
        )

    print("-" * 90)
    print(f"Total: {len(tasks)} tasks")
    print(f"\nRoles available: {', '.join(loader.get_roles())}")


def show_statistics(loader: TACLoader) -> None:
    """Print dataset statistics."""
    stats = loader.get_statistics()

    print("\nTAC Dataset Statistics")
    print("=" * 50)
    print(f"Total tasks: {stats['total_tasks']}")

    print("\nBy Role:")
    for role, count in stats.get("role_distribution", {}).items():
        print(f"  {role}: {count}")

    print("\nBy Difficulty:")
    for diff, count in stats.get("difficulty_distribution", {}).items():
        if count > 0:
            print(f"  {diff}: {count}")

    print("\nBy MCP Value:")
    for value, count in stats.get("mcp_value_distribution", {}).items():
        if count > 0:
            print(f"  {value}: {count}")

    print("\nBy Grading Type:")
    for gtype, count in stats.get("grading_type_distribution", {}).items():
        if count > 0:
            print(f"  {gtype}: {count}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Harbor-compatible tasks from TAC benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python run_adapter.py --output_dir ./output
    python run_adapter.py --role SWE --limit 5 --output_dir ./output
    python run_adapter.py --task tac-implement-hyperloglog --output_dir ./output
    python run_adapter.py --list
        """,
    )

    parser.add_argument(
        "--output_dir", "-o",
        type=str,
        help="Output directory for generated tasks (required for generation)",
    )

    parser.add_argument(
        "--data_dir", "-d",
        type=str,
        default=None,
        help="Data directory containing TAC task definitions (optional, uses curated list if not provided)",
    )

    parser.add_argument(
        "--role", "-r",
        type=str,
        choices=list(TAC_ROLES),
        default=None,
        help="Filter tasks by role (SWE, PM, DS, HR, Finance, Admin)",
    )

    parser.add_argument(
        "--limit", "-n",
        type=int,
        default=None,
        help="Maximum number of tasks to generate",
    )

    parser.add_argument(
        "--task", "-t",
        type=str,
        default=None,
        help="Generate a specific task by ID (Harbor ID or TAC ID)",
    )

    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all available tasks",
    )

    parser.add_argument(
        "--stats", "-s",
        action="store_true",
        help="Show dataset statistics",
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    # Initialize loader
    loader = TACLoader(args.data_dir)

    # Handle list command
    if args.list:
        list_tasks(loader)
        return 0

    # Handle stats command
    if args.stats:
        show_statistics(loader)
        return 0

    # Require output_dir for task generation
    if not args.output_dir:
        parser.print_help()
        print("\nError: --output_dir is required for task generation")
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize adapter
    adapter = TACAdapter(output_dir, args.data_dir)

    # Generate specific task
    if args.task:
        print(f"Generating task: {args.task}")
        try:
            path = adapter.generate_task(args.task)
            print(f"Generated: {path}")
            return 0
        except ValueError as e:
            print(f"Error: {e}")
            return 1

    # Generate tasks with filters
    if args.role:
        print(f"Generating tasks for role: {args.role}")
    else:
        print("Generating all tasks")

    if args.limit:
        print(f"Limiting to {args.limit} tasks")

    paths = adapter.generate_all_tasks(
        role_filter=args.role,
        limit=args.limit,
    )

    print(f"\nGenerated {len(paths)} tasks:")
    for path in paths:
        if args.verbose:
            print(f"  - {path}")
        else:
            print(f"  - {path.name}")

    print(f"\nOutput directory: {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
