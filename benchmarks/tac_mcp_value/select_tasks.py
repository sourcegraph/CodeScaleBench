#!/usr/bin/env python3
# NOTE: This script requires the Dashboard repo's src/ on PYTHONPATH to run.
# export PYTHONPATH="/path/to/CodeContextBench_Dashboard:$PYTHONPATH"
"""
Score and select top tasks from TAC (TheAgentCompany) using MCPValueScorer.

Uses the MCP Value Scorer to rank tasks based on their potential benefit
from MCP-enabled tools (semantic search, cross-file navigation, etc.).

TAC tasks that involve code understanding, implementation in large codebases,
or finding information across repositories tend to score higher as they
benefit most from MCP tools.

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

from benchmarks.tac_mcp_value.adapter import TACLoader, TACTask
from src.task_selection.mcp_value_scorer import MCPValueScorer, ScoredTask


def task_to_scorer_dict(task: TACTask) -> dict[str, Any]:
    """
    Convert a TACTask to a dictionary format suitable for MCPValueScorer.

    MCPValueScorer expects tasks with fields like:
    - id, task_id: task identifier
    - description: task description text
    - category: task category for weighting
    - requirements, acceptance_criteria: for complexity scoring
    - files_changed, num_files: for cross-file scoring
    - estimated_tokens: for context complexity

    Args:
        task: TACTask instance.

    Returns:
        Dictionary formatted for MCPValueScorer.
    """
    # Build rich description from task fields
    description = task.description
    if task.title:
        description = f"{task.title}. {description}"

    # Map MCP value to search indicators
    search_hint = ""
    if task.mcp_value in ("high", "very-high"):
        search_hint = " Requires understanding codebase architecture and patterns."
    elif task.mcp_value == "medium":
        search_hint = " Involves cross-file understanding."

    scorer_dict: dict[str, Any] = {
        "id": task.id,
        "task_id": task.id,
        "description": description + search_hint,
        "instructions": task.description,
        # Map TAC task types to scorer categories
        "category": _map_task_to_category(task),
        "role": task.role,
        "tac_id": task.tac_id,
        "difficulty": task.difficulty,
        "mcp_value": task.mcp_value,
        "grading_type": task.grading_type,
        "language": task.language,
        "dependencies": task.dependencies,
        # Include metadata
        "metadata": task.metadata,
    }

    # Set cross-module indicator based on task type
    if task.mcp_value in ("high", "very-high"):
        scorer_dict["cross_module"] = True
        scorer_dict["cross_file"] = True
        scorer_dict["num_files"] = 10  # Complex tasks touch many files

    # Estimate tokens based on difficulty
    if task.difficulty == "hard":
        scorer_dict["estimated_tokens"] = 8000
    elif task.difficulty == "medium":
        scorer_dict["estimated_tokens"] = 4000
    else:
        scorer_dict["estimated_tokens"] = 2000

    # Tasks involving finding answers in codebase have explicit search needs
    if "find" in task.tac_id or "answer" in task.tac_id or "codebase" in task.tac_id:
        # Boost semantic search scoring with explicit keywords
        scorer_dict["description"] += " Search and find specific information in repository."

    return scorer_dict


def _map_task_to_category(task: TACTask) -> str:
    """
    Map TAC task to MCPValueScorer category for proper weighting.

    Args:
        task: TACTask instance.

    Returns:
        Category string for scorer.
    """
    tac_id_lower = task.tac_id.lower()

    # Implementation tasks
    if "implement" in tac_id_lower:
        if "buffer-pool" in tac_id_lower or "hyperloglog" in tac_id_lower:
            return "architecture"  # Complex system implementation
        return "feature"

    # Finding/searching tasks
    if "find" in tac_id_lower or "answer" in tac_id_lower:
        return "debugging"  # Search tasks benefit like debugging from semantic search

    # Dependency/configuration tasks
    if "dependency" in tac_id_lower:
        return "integration"

    # Test writing tasks
    if "test" in tac_id_lower or "unit-test" in tac_id_lower:
        return "testing"

    # Troubleshooting tasks
    if "troubleshoot" in tac_id_lower or "debug" in tac_id_lower:
        return "debugging"

    # API/endpoint tasks
    if "endpoint" in tac_id_lower or "api" in tac_id_lower:
        return "api_design"

    # Default based on role
    if task.role == "SWE":
        return "feature"
    return "default"


def select_tasks(
    loader: TACLoader,
    top_n: int = 20,
    min_score: float = 0.0,
    role: str | None = None,
    difficulty: str | None = None,
    mcp_value: str | None = None,
) -> list[ScoredTask]:
    """
    Select top tasks from TAC using MCP Value Scorer.

    Args:
        loader: TACLoader instance.
        top_n: Number of top tasks to select.
        min_score: Minimum score threshold.
        role: Optional role filter (SWE, PM, DS, HR, Finance, Admin).
        difficulty: Optional difficulty filter (easy, medium, hard).
        mcp_value: Optional MCP value filter (low, medium, high, very-high).

    Returns:
        List of ScoredTask objects ranked by MCP value.
    """
    # Load all tasks
    tasks = loader.load()

    # Apply filters
    if role:
        tasks = loader.filter_by_role(role)
    if difficulty:
        tasks = loader.filter_by_difficulty(difficulty)
    if mcp_value:
        tasks = loader.filter_by_mcp_value(mcp_value)

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
    print(f"\n=== TAC Task Selection Summary ===")
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

    # Role distribution
    roles: dict[str, int] = {}
    for task in selected_tasks:
        role = task.task.get("role", "unknown")
        roles[role] = roles.get(role, 0) + 1

    print(f"\n=== Role Distribution ===")
    for role, count in sorted(roles.items(), key=lambda x: -x[1]):
        print(f"  {role}: {count}")

    # Difficulty distribution
    difficulties: dict[str, int] = {}
    for task in selected_tasks:
        diff = task.task.get("difficulty", "unknown")
        difficulties[diff] = difficulties.get(diff, 0) + 1

    print(f"\n=== Difficulty Distribution ===")
    for diff, count in sorted(difficulties.items(), key=lambda x: -x[1]):
        print(f"  {diff}: {count}")

    # MCP value distribution
    mcp_values: dict[str, int] = {}
    for task in selected_tasks:
        val = task.task.get("mcp_value", "unknown")
        mcp_values[val] = mcp_values.get(val, 0) + 1

    print(f"\n=== MCP Value Distribution ===")
    for val, count in sorted(mcp_values.items(), key=lambda x: -x[1]):
        print(f"  {val}: {count}")

    # Grading type distribution
    grading_types: dict[str, int] = {}
    for task in selected_tasks:
        gt = task.task.get("grading_type", "unknown")
        grading_types[gt] = grading_types.get(gt, 0) + 1

    print(f"\n=== Grading Type Distribution ===")
    for gt, count in sorted(grading_types.items(), key=lambda x: -x[1]):
        print(f"  {gt}: {count}")

    # Top 10 tasks
    print(f"\n=== Top 10 Selected Tasks ===")
    for i, task in enumerate(selected_tasks[:10], 1):
        tac_id = task.task.get("tac_id", task.task_id)[:35]
        mcp = task.task.get("mcp_value", "")
        grading = task.task.get("grading_type", "")
        print(
            f"{i:2}. {tac_id:<35} "
            f"score={task.total_score:.4f} "
            f"mcp={mcp:<10} "
            f"grading={grading}"
        )


def main() -> int:
    """Main entry point for task selection."""
    parser = argparse.ArgumentParser(
        description="Select top TAC tasks using MCP Value Scorer"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Path to TAC data directory (default: uses built-in curated tasks)",
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
        "--role",
        type=str,
        default=None,
        help="Filter by role (SWE, PM, DS, HR, Finance, Admin)",
    )
    parser.add_argument(
        "--difficulty",
        type=str,
        default=None,
        help="Filter by difficulty (easy, medium, hard)",
    )
    parser.add_argument(
        "--mcp-value",
        type=str,
        default=None,
        help="Filter by MCP value (low, medium, high, very-high)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress summary output",
    )

    args = parser.parse_args()

    # Determine paths
    script_dir = Path(__file__).parent
    data_dir = args.data_dir  # Can be None to use built-in curated tasks
    output_path = args.output or script_dir / "selected_tasks.json"

    # Load and select
    loader = TACLoader(data_dir)
    tasks = loader.load()
    total_count = len(tasks)

    selected = select_tasks(
        loader=loader,
        top_n=args.top_n,
        min_score=args.min_score,
        role=args.role,
        difficulty=args.difficulty,
        mcp_value=args.mcp_value,
    )

    # Print summary
    if not args.quiet:
        print_selection_summary(total_count, selected)

    # Build output data
    output_data = {
        "benchmark": "tac_mcp_value",
        "selection_criteria": {
            "scorer": "MCPValueScorer",
            "top_n": args.top_n,
            "min_score": args.min_score,
            "role_filter": args.role,
            "difficulty_filter": args.difficulty,
            "mcp_value_filter": args.mcp_value,
        },
        "statistics": {
            "total_tasks": total_count,
            "selected_tasks": len(selected),
            "avg_score": sum(t.total_score for t in selected) / len(selected) if selected else 0.0,
        },
        "tasks": [
            {
                "task_id": t.task_id,
                "tac_id": t.task.get("tac_id", ""),
                "score": round(t.total_score, 4),
                "breakdown": {k: round(v, 4) for k, v in t.breakdown.items()},
                "role": t.task.get("role", ""),
                "difficulty": t.task.get("difficulty", ""),
                "mcp_value": t.task.get("mcp_value", ""),
                "grading_type": t.task.get("grading_type", ""),
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
