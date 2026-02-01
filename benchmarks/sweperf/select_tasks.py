#!/usr/bin/env python3
# NOTE: This script requires the Dashboard repo's src/ on PYTHONPATH to run.
# export PYTHONPATH="/path/to/CodeContextBench_Dashboard:$PYTHONPATH"
"""
Score and select top tasks from SWE-Perf using MCPValueScorer.

Uses the MCP Value Scorer to rank tasks based on their potential benefit
from MCP-enabled tools (semantic search, cross-file navigation, etc.).

SWE-Perf tasks that involve understanding existing code patterns,
multiple optimization hints, or complex repositories tend to score higher
as they benefit more from MCP tools.

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

from benchmarks.sweperf.adapter import SWEPerfLoader, SWEPerfTask
from src.task_selection.mcp_value_scorer import MCPValueScorer, ScoredTask


def task_to_scorer_dict(task: SWEPerfTask) -> dict[str, Any]:
    """
    Convert a SWEPerfTask to a dictionary format suitable for MCPValueScorer.

    MCPValueScorer expects tasks with fields like:
    - id, task_id: task identifier
    - description: task description text
    - category: task category for weighting
    - requirements, acceptance_criteria: for complexity scoring
    - files_changed, num_files: for cross-file scoring
    - estimated_tokens: for context complexity

    Args:
        task: SWEPerfTask instance.

    Returns:
        Dictionary formatted for MCPValueScorer.
    """
    # Map SWE-Perf fields to scorer expectations
    description = task.description
    if task.target_function:
        description += f" Optimize function: {task.target_function}."
    if task.optimization_hints:
        description += " Hints: " + "; ".join(task.optimization_hints)

    scorer_dict: dict[str, Any] = {
        "id": task.id,
        "task_id": task.id,
        "description": description,
        "instructions": f"Optimize {task.target_function} for better runtime performance.",
        "category": "refactoring",  # Performance optimization is a form of refactoring
        "repo_name": task.repo_name,
        "target_function": task.target_function,
        "difficulty": task.difficulty,
        "baseline_runtime": task.baseline_runtime,
        # Optimization hints as requirements
        "requirements": [{"hint": h} for h in task.optimization_hints],
        "acceptance_criteria": task.optimization_hints,
        # Include metadata
        "metadata": task.metadata,
    }

    # Performance tasks typically require understanding the codebase
    # to find optimization opportunities
    optimization_category = task.get_optimization_category()
    if optimization_category in ["algorithmic", "vectorization", "parallelization"]:
        # These optimizations often require understanding larger code context
        scorer_dict["cross_module"] = True
        scorer_dict["num_files"] = 3  # Likely need to look at related files

    # Higher baseline runtime = potentially more complex function
    if task.baseline_runtime > 1.0:  # More than 1 second
        scorer_dict["estimated_tokens"] = 5000
    elif task.baseline_runtime > 0.1:
        scorer_dict["estimated_tokens"] = 3000
    else:
        scorer_dict["estimated_tokens"] = 1500

    # If multiple optimization hints, task is likely more complex
    if len(task.optimization_hints) > 2:
        scorer_dict["cross_file"] = True

    return scorer_dict


def select_tasks(
    loader: SWEPerfLoader,
    top_n: int = 20,
    min_score: float = 0.0,
    repo: str | None = None,
    difficulty: str | None = None,
) -> list[ScoredTask]:
    """
    Select top tasks from SWE-Perf using MCP Value Scorer.

    Args:
        loader: SWEPerfLoader instance.
        top_n: Number of top tasks to select.
        min_score: Minimum score threshold.
        repo: Optional repository name filter.
        difficulty: Optional difficulty filter (easy, medium, hard).

    Returns:
        List of ScoredTask objects ranked by MCP value.
    """
    # Load all tasks
    tasks = loader.load()

    # Apply filters
    if repo:
        tasks = loader.filter_by_repo(repo)
    if difficulty:
        tasks = loader.filter_by_difficulty(difficulty)

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
    print(f"\n=== SWE-Perf Task Selection Summary ===")
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

    # Repository distribution
    repos: dict[str, int] = {}
    for task in selected_tasks:
        repo = task.task.get("repo_name", "unknown")
        repos[repo] = repos.get(repo, 0) + 1

    print(f"\n=== Repository Distribution ===")
    for repo, count in sorted(repos.items(), key=lambda x: -x[1]):
        print(f"  {repo}: {count}")

    # Difficulty distribution
    difficulties: dict[str, int] = {}
    for task in selected_tasks:
        diff = task.task.get("difficulty", "unknown")
        difficulties[diff] = difficulties.get(diff, 0) + 1

    print(f"\n=== Difficulty Distribution ===")
    for diff, count in sorted(difficulties.items(), key=lambda x: -x[1]):
        print(f"  {diff}: {count}")

    # Baseline runtime statistics
    runtimes = [task.task.get("baseline_runtime", 0) for task in selected_tasks]
    avg_runtime = sum(runtimes) / len(runtimes) if runtimes else 0

    print(f"\n=== Baseline Runtime Statistics ===")
    print(f"  Average: {avg_runtime:.4f}s")
    print(f"  Max: {max(runtimes) if runtimes else 0:.4f}s")
    print(f"  Min: {min(runtimes) if runtimes else 0:.4f}s")

    # Top 10 tasks
    print(f"\n=== Top 10 Selected Tasks ===")
    for i, task in enumerate(selected_tasks[:10], 1):
        func = task.task.get("target_function", "")[:30]
        repo = task.task.get("repo_name", "")
        runtime = task.task.get("baseline_runtime", 0)
        print(
            f"{i:2}. {task.task_id[:35]:<35} "
            f"score={task.total_score:.4f} "
            f"repo={repo:<12} "
            f"runtime={runtime:.3f}s"
        )


def main() -> int:
    """Main entry point for task selection."""
    parser = argparse.ArgumentParser(
        description="Select top SWE-Perf tasks using MCP Value Scorer"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Path to SWE-Perf data directory (default: benchmarks/sweperf/data)",
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
        "--repo",
        type=str,
        default=None,
        help="Filter by repository name (e.g., numpy, scikit-learn)",
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
    loader = SWEPerfLoader(data_dir)
    tasks = loader.load()
    total_count = len(tasks)

    selected = select_tasks(
        loader=loader,
        top_n=args.top_n,
        min_score=args.min_score,
        repo=args.repo,
        difficulty=args.difficulty,
    )

    # Print summary
    if not args.quiet:
        print_selection_summary(total_count, selected)

    # Build output data
    output_data = {
        "benchmark": "sweperf",
        "selection_criteria": {
            "scorer": "MCPValueScorer",
            "top_n": args.top_n,
            "min_score": args.min_score,
            "repo_filter": args.repo,
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
                "repo_name": t.task.get("repo_name", ""),
                "target_function": t.task.get("target_function", ""),
                "difficulty": t.task.get("difficulty", ""),
                "baseline_runtime": t.task.get("baseline_runtime", 0),
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
