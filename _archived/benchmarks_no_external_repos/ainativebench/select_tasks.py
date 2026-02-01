#!/usr/bin/env python3
# NOTE: This script requires the Dashboard repo's src/ on PYTHONPATH to run.
# export PYTHONPATH="/path/to/CodeContextBench_Dashboard:$PYTHONPATH"
"""
Score and select top tasks from AINativeBench using MCPValueScorer.

Uses the MCP Value Scorer to rank tasks based on their potential benefit
from MCP-enabled tools (semantic search, cross-file navigation, etc.).

Outputs the top tasks ranked by MCP value score to selected_tasks.json.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from benchmarks.ainativebench.adapter import AINativeBenchLoader, AINativeBenchTask
from src.task_selection.mcp_value_scorer import MCPValueScorer, ScoredTask


def task_to_scorer_dict(task: AINativeBenchTask) -> dict[str, Any]:
    """
    Convert an AINativeBenchTask to a dictionary format suitable for MCPValueScorer.

    MCPValueScorer expects tasks with fields like:
    - id, task_id: task identifier
    - description: task description text
    - category: task category for weighting
    - requirements, acceptance_criteria: for complexity scoring
    - files_changed, num_files: for cross-file scoring
    - estimated_tokens: for context complexity

    Args:
        task: AINativeBenchTask instance.

    Returns:
        Dictionary formatted for MCPValueScorer.
    """
    # Map AINativeBench fields to scorer expectations
    scorer_dict: dict[str, Any] = {
        "id": task.id,
        "task_id": task.id,
        "description": task.description,
        "category": task.benchmark_name,  # Use benchmark as category
        "variant": task.variant,
        "language": task.language,
        # Map test_cases to requirements for complexity scoring
        "requirements": [tc.to_dict() for tc in task.test_cases],
        # Context files indicate cross-file dependencies
        "files_changed": task.context_files,
        "num_files": len(task.context_files),
        # Include metadata
        "metadata": task.metadata,
    }

    # Add variant-specific indicators
    if task.variant == "retrieval":
        # Retrieval tasks benefit more from semantic search
        scorer_dict["cross_module"] = True
        # Add search-related description for semantic search scoring
        if "retrieval" not in task.description.lower():
            scorer_dict["description"] += " Requires context retrieval and search."

    if task.variant == "hard":
        # Hard tasks typically have more context complexity
        scorer_dict["estimated_tokens"] = 8000

    return scorer_dict


def select_tasks(
    loader: AINativeBenchLoader,
    top_n: int = 20,
    min_score: float = 0.0,
    benchmark: str | None = None,
    variant: str | None = None,
) -> list[ScoredTask]:
    """
    Select top tasks from AINativeBench using MCP Value Scorer.

    Args:
        loader: AINativeBenchLoader instance.
        top_n: Number of top tasks to select.
        min_score: Minimum score threshold.
        benchmark: Optional benchmark name filter.
        variant: Optional variant filter.

    Returns:
        List of ScoredTask objects ranked by MCP value.
    """
    # Load all tasks
    tasks = loader.load()

    # Apply filters
    if benchmark:
        tasks = loader.filter_by_benchmark(benchmark)
    if variant:
        tasks = loader.filter_by_variant(variant)

    if not tasks:
        return []

    # Convert to scorer format
    scorer_dicts = [task_to_scorer_dict(task) for task in tasks]

    # Score and select
    scorer = MCPValueScorer()
    selected = scorer.select_top_tasks(scorer_dicts, n=top_n, min_score=min_score)

    return selected


def print_selection_summary(
    total_count: int,
    selected_tasks: list[ScoredTask],
) -> None:
    """Print summary of selection process to stdout."""
    print(f"\n=== AINativeBench Task Selection Summary ===")
    print(f"Total tasks loaded: {total_count}")
    print(f"Tasks selected: {len(selected_tasks)}")

    if not selected_tasks:
        print("\nNo tasks selected!")
        return

    # Calculate statistics
    avg_score = sum(t.total_score for t in selected_tasks) / len(selected_tasks)
    max_score = max(t.total_score for t in selected_tasks)
    min_selected_score = min(t.total_score for t in selected_tasks)

    print(f"\n=== Selection Statistics ===")
    print(f"Average MCP score: {avg_score:.4f}")
    print(f"Score range: {min_selected_score:.4f} - {max_score:.4f}")

    # Category (benchmark) distribution
    benchmarks: dict[str, int] = {}
    for task in selected_tasks:
        bench = task.task.get("category", "unknown")
        benchmarks[bench] = benchmarks.get(bench, 0) + 1

    print(f"\n=== Benchmark Distribution ===")
    for bench, count in sorted(benchmarks.items(), key=lambda x: -x[1]):
        print(f"  {bench}: {count}")

    # Variant distribution
    variants: dict[str, int] = {}
    for task in selected_tasks:
        var = task.task.get("variant", "unknown")
        variants[var] = variants.get(var, 0) + 1

    print(f"\n=== Variant Distribution ===")
    for var, count in sorted(variants.items(), key=lambda x: -x[1]):
        print(f"  {var}: {count}")

    # Top 10 tasks
    print(f"\n=== Top 10 Selected Tasks ===")
    for i, task in enumerate(selected_tasks[:10], 1):
        print(
            f"{i:2}. {task.task_id[:50]:<50} "
            f"score={task.total_score:.4f}"
        )


def main() -> int:
    """Main entry point for task selection."""
    parser = argparse.ArgumentParser(
        description="Select top AINativeBench tasks using MCP Value Scorer"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Path to AINativeBench data directory (default: benchmarks/ainativebench/data)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output path for selected_tasks.json (default: same directory as script)",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=20,
        help="Number of top tasks to select (default: 20)",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="Minimum MCP score threshold (default: 0.0)",
    )
    parser.add_argument(
        "--benchmark",
        type=str,
        default=None,
        help="Filter by benchmark name (e.g., repobench, crosscodeeval)",
    )
    parser.add_argument(
        "--variant",
        type=str,
        default=None,
        help="Filter by variant (easy, medium, hard, retrieval)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress summary output",
    )

    args = parser.parse_args()

    # Determine paths
    script_dir = Path(__file__).parent
    data_dir = args.data_dir or script_dir / "data"
    output_path = args.output or script_dir / "selected_tasks.json"

    # Check data directory
    if not data_dir.exists():
        print(f"Warning: Data directory not found: {data_dir}", file=sys.stderr)
        print("Will attempt to load with empty dataset.", file=sys.stderr)

    # Load and select
    loader = AINativeBenchLoader(data_dir)
    tasks = loader.load()
    total_count = len(tasks)

    selected = select_tasks(
        loader=loader,
        top_n=args.top_n,
        min_score=args.min_score,
        benchmark=args.benchmark,
        variant=args.variant,
    )

    # Print summary
    if not args.quiet:
        print_selection_summary(total_count, selected)

    # Build output data
    output_data = {
        "benchmark": "ainativebench",
        "selection_criteria": {
            "scorer": "MCPValueScorer",
            "top_n": args.top_n,
            "min_score": args.min_score,
            "benchmark_filter": args.benchmark,
            "variant_filter": args.variant,
        },
        "statistics": {
            "total_tasks": total_count,
            "selected_tasks": len(selected),
            "avg_score": sum(t.total_score for t in selected) / len(selected) if selected else 0.0,
        },
        "tasks": [
            {
                "task_id": t.task_id,
                "score": round(t.total_score, 4),
                "breakdown": {k: round(v, 4) for k, v in t.breakdown.items()},
                "benchmark": t.task.get("category", ""),
                "variant": t.task.get("variant", ""),
                "language": t.task.get("language", ""),
            }
            for t in selected
        ],
    }

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    if not args.quiet:
        print(f"\nWrote {len(selected)} selected tasks to {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
