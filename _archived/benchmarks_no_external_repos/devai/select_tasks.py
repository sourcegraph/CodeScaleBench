#!/usr/bin/env python3
# NOTE: This script requires the Dashboard repo's src/ on PYTHONPATH to run.
# export PYTHONPATH="/path/to/CodeContextBench_Dashboard:$PYTHONPATH"
"""
Score and select top tasks from DevAI using MCPValueScorer.

Uses the MCP Value Scorer to rank tasks based on their potential benefit
from MCP-enabled tools (semantic search, cross-file navigation, etc.).

DevAI tasks with hierarchical requirements and complex dependencies
tend to score higher as they benefit more from MCP tools.

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

from benchmarks.devai.adapter import DevAILoader, DevAITask
from src.task_selection.mcp_value_scorer import MCPValueScorer, ScoredTask


def task_to_scorer_dict(task: DevAITask) -> dict[str, Any]:
    """
    Convert a DevAITask to a dictionary format suitable for MCPValueScorer.

    MCPValueScorer expects tasks with fields like:
    - id, task_id: task identifier
    - description: task description text
    - category: task category for weighting
    - requirements, acceptance_criteria: for complexity scoring
    - files_changed, num_files: for cross-file scoring
    - estimated_tokens: for context complexity

    Args:
        task: DevAITask instance.

    Returns:
        Dictionary formatted for MCPValueScorer.
    """
    # Map DevAI fields to scorer expectations
    scorer_dict: dict[str, Any] = {
        "id": task.id,
        "task_id": task.id,
        "description": task.user_query + " " + task.description,
        "category": task.domain,  # Use domain as category
        "domain": task.domain,
        # Requirements list for complexity scoring
        "requirements": [r.to_dict() for r in task.requirements],
        "acceptance_criteria": [r.description for r in task.requirements],
        # Preferences provide additional context
        "preferences": [p.to_dict() for p in task.preferences],
        # Include metadata
        "metadata": task.metadata,
    }

    # Analyze requirement dependencies for cross-file scoring
    # Tasks with hierarchical requirements tend to need cross-file understanding
    deps_count = sum(len(r.dependencies) for r in task.requirements)
    if deps_count > 5:
        scorer_dict["cross_module"] = True
        scorer_dict["num_files"] = deps_count  # Proxy for complexity

    # Estimate tokens based on task complexity
    token_estimate = len(task.user_query) + len(task.description)
    token_estimate += sum(len(r.description) for r in task.requirements) * 2
    scorer_dict["estimated_tokens"] = token_estimate

    return scorer_dict


def select_tasks(
    loader: DevAILoader,
    top_n: int = 20,
    min_score: float = 0.0,
    domain: str | None = None,
) -> list[ScoredTask]:
    """
    Select top tasks from DevAI using MCP Value Scorer.

    Args:
        loader: DevAILoader instance.
        top_n: Number of top tasks to select.
        min_score: Minimum score threshold.
        domain: Optional domain filter.

    Returns:
        List of ScoredTask objects ranked by MCP value.
    """
    # Load all tasks
    tasks = loader.load()

    # Apply filters
    if domain:
        tasks = loader.filter_by_domain(domain)

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
    print(f"\n=== DevAI Task Selection Summary ===")
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

    # Domain distribution
    domains: dict[str, int] = {}
    for task in selected_tasks:
        dom = task.task.get("domain", "unknown")
        domains[dom] = domains.get(dom, 0) + 1

    print(f"\n=== Domain Distribution ===")
    for dom, count in sorted(domains.items(), key=lambda x: -x[1]):
        print(f"  {dom}: {count}")

    # Requirements count distribution
    req_counts = [len(task.task.get("requirements", [])) for task in selected_tasks]
    avg_reqs = sum(req_counts) / len(req_counts) if req_counts else 0

    print(f"\n=== Requirements Statistics ===")
    print(f"  Average requirements per task: {avg_reqs:.1f}")
    print(f"  Max requirements: {max(req_counts) if req_counts else 0}")
    print(f"  Min requirements: {min(req_counts) if req_counts else 0}")

    # Top 10 tasks
    print(f"\n=== Top 10 Selected Tasks ===")
    for i, task in enumerate(selected_tasks[:10], 1):
        domain = task.task.get("domain", "")
        req_count = len(task.task.get("requirements", []))
        print(
            f"{i:2}. {task.task_id[:40]:<40} "
            f"score={task.total_score:.4f} "
            f"domain={domain:<10} "
            f"reqs={req_count}"
        )


def main() -> int:
    """Main entry point for task selection."""
    parser = argparse.ArgumentParser(
        description="Select top DevAI tasks using MCP Value Scorer"
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Path to DevAI data directory (default: benchmarks/devai/data)",
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
        "--domain",
        type=str,
        default=None,
        help="Filter by domain (web, cli, data, automation, api, ml, testing, devops)",
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
    loader = DevAILoader(data_dir)
    tasks = loader.load()
    total_count = len(tasks)

    selected = select_tasks(
        loader=loader,
        top_n=args.top_n,
        min_score=args.min_score,
        domain=args.domain,
    )

    # Print summary
    if not args.quiet:
        print_selection_summary(total_count, selected)

    # Build output data
    output_data = {
        "benchmark": "devai",
        "selection_criteria": {
            "scorer": "MCPValueScorer",
            "top_n": args.top_n,
            "min_score": args.min_score,
            "domain_filter": args.domain,
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
                "domain": t.task.get("domain", ""),
                "requirements_count": len(t.task.get("requirements", [])),
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
