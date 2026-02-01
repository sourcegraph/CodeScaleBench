#!/usr/bin/env python3
# NOTE: This script requires the Dashboard repo's src/ on PYTHONPATH to run.
# export PYTHONPATH="/path/to/CodeContextBench_Dashboard:$PYTHONPATH"
"""
Score and select top tasks from PRDBench using MCPValueScorer.

Uses the MCP Value Scorer to rank tasks based on their potential benefit
from MCP-enabled tools (semantic search, cross-file navigation, etc.).

PRDBench tasks with complex PRDs and multiple evaluation criteria
tend to score higher as they benefit more from MCP tools for understanding
requirements and implementing features across multiple components.

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

from benchmarks.prdbench.adapter import PRDBenchLoader, PRDBenchTask
from src.task_selection.mcp_value_scorer import MCPValueScorer, ScoredTask


def task_to_scorer_dict(task: PRDBenchTask) -> dict[str, Any]:
    """
    Convert a PRDBenchTask to a dictionary format suitable for MCPValueScorer.

    MCPValueScorer expects tasks with fields like:
    - id, task_id: task identifier
    - description: task description text
    - category: task category for weighting
    - requirements, acceptance_criteria: for complexity scoring
    - files_changed, num_files: for cross-file scoring
    - estimated_tokens: for context complexity

    Args:
        task: PRDBenchTask instance.

    Returns:
        Dictionary formatted for MCPValueScorer.
    """
    # Map PRDBench fields to scorer expectations
    scorer_dict: dict[str, Any] = {
        "id": task.id,
        "task_id": task.id,
        "description": task.description or task.prd_content[:500],
        "category": "feature",  # PRDBench tasks are feature implementations
        "title": task.title,
        "difficulty": task.difficulty,
        # Map evaluation criteria to requirements for complexity scoring
        "requirements": [c.to_dict() for c in task.evaluation_criteria],
        "acceptance_criteria": [c.description for c in task.evaluation_criteria],
        # Include metadata
        "metadata": task.metadata,
    }

    # Estimate tokens from PRD content
    token_estimate = len(task.prd_content) // 4  # Rough chars to tokens
    scorer_dict["estimated_tokens"] = token_estimate

    # PRD-based tasks typically involve cross-module work
    # More criteria = more components to implement
    criteria_count = len(task.evaluation_criteria)
    if criteria_count > 5:
        scorer_dict["cross_module"] = True
        scorer_dict["num_files"] = criteria_count * 2  # Estimate files from criteria

    # Categorize by evaluation criteria categories
    if task.test_plan:
        categories = set(c.category for c in task.test_plan.criteria)
        if len(categories) > 2:
            # Multiple category types = more diverse implementation
            scorer_dict["cross_file"] = True

    return scorer_dict


def select_tasks(
    loader: PRDBenchLoader,
    top_n: int = 20,
    min_score: float = 0.0,
    difficulty: str | None = None,
) -> list[ScoredTask]:
    """
    Select top tasks from PRDBench using MCP Value Scorer.

    Args:
        loader: PRDBenchLoader instance.
        top_n: Number of top tasks to select.
        min_score: Minimum score threshold.
        difficulty: Optional difficulty filter (easy, medium, hard).

    Returns:
        List of ScoredTask objects ranked by MCP value.
    """
    # Load all tasks
    tasks = loader.load()

    # Apply filters
    if difficulty:
        difficulty_lower = difficulty.lower()
        tasks = [t for t in tasks if t.difficulty == difficulty_lower]

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
    print(f"\n=== PRDBench Task Selection Summary ===")
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

    # Difficulty distribution
    difficulties: dict[str, int] = {}
    for task in selected_tasks:
        diff = task.task.get("difficulty", "unknown")
        difficulties[diff] = difficulties.get(diff, 0) + 1

    print(f"\n=== Difficulty Distribution ===")
    for diff, count in sorted(difficulties.items(), key=lambda x: -x[1]):
        print(f"  {diff}: {count}")

    # Criteria count statistics
    criteria_counts = [len(task.task.get("requirements", [])) for task in selected_tasks]
    avg_criteria = sum(criteria_counts) / len(criteria_counts) if criteria_counts else 0

    print(f"\n=== Evaluation Criteria Statistics ===")
    print(f"  Average criteria per task: {avg_criteria:.1f}")
    print(f"  Max criteria: {max(criteria_counts) if criteria_counts else 0}")
    print(f"  Min criteria: {min(criteria_counts) if criteria_counts else 0}")

    # Token estimate statistics
    token_estimates = [task.task.get("estimated_tokens", 0) for task in selected_tasks]
    avg_tokens = sum(token_estimates) / len(token_estimates) if token_estimates else 0

    print(f"\n=== PRD Size Statistics ===")
    print(f"  Average estimated tokens: {avg_tokens:,.0f}")
    print(f"  Max tokens: {max(token_estimates) if token_estimates else 0:,}")

    # Top 10 tasks
    print(f"\n=== Top 10 Selected Tasks ===")
    for i, task in enumerate(selected_tasks[:10], 1):
        title = task.task.get("title", task.task_id)[:40]
        criteria = len(task.task.get("requirements", []))
        print(
            f"{i:2}. {title:<40} "
            f"score={task.total_score:.4f} "
            f"criteria={criteria}"
        )


def main() -> int:
    """Main entry point for task selection."""
    parser = argparse.ArgumentParser(
        description="Select top PRDBench tasks using MCP Value Scorer"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Path to PRDBench data directory (default: benchmarks/prdbench/data)",
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
        "--difficulty",
        type=str,
        default=None,
        help="Filter by difficulty (easy, medium, hard)",
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
    loader = PRDBenchLoader(data_dir)
    tasks = loader.load()
    total_count = len(tasks)

    selected = select_tasks(
        loader=loader,
        top_n=args.top_n,
        min_score=args.min_score,
        difficulty=args.difficulty,
    )

    # Print summary
    if not args.quiet:
        print_selection_summary(total_count, selected)

    # Build output data
    output_data = {
        "benchmark": "prdbench",
        "selection_criteria": {
            "scorer": "MCPValueScorer",
            "top_n": args.top_n,
            "min_score": args.min_score,
            "difficulty_filter": args.difficulty,
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
                "title": t.task.get("title", ""),
                "difficulty": t.task.get("difficulty", ""),
                "criteria_count": len(t.task.get("requirements", [])),
                "estimated_tokens": t.task.get("estimated_tokens", 0),
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
