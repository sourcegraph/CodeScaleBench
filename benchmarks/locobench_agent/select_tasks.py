#!/usr/bin/env python3
# NOTE: This script requires the Dashboard repo's src/ on PYTHONPATH to run.
# export PYTHONPATH="/path/to/CodeContextBench_Dashboard:$PYTHONPATH"
"""
Score and select top tasks from LoCoBench-Agent dataset.

Implements the task selection criteria defined in docs/TASK_SELECTION_CRITERIA.md:
- Minimum thresholds: context_length > 50K tokens, files_count > 5
- Scoring weights: context_length (0.3), files_count (0.3), task_category_bonus (0.4)
- Category bonuses: architectural_understanding=1.0, cross_file_refactoring=0.9, etc.

Outputs the top 50 tasks ranked by score to selected_tasks.json.
"""

import json
import sys
from pathlib import Path
from typing import Any

# Minimum thresholds for task selection
MIN_CONTEXT_LENGTH = 50_000  # tokens
MIN_FILES_COUNT = 5

# Scoring weights
CONTEXT_WEIGHT = 0.3
FILES_WEIGHT = 0.3
CATEGORY_WEIGHT = 0.4

# Task category bonuses (0-1 scale)
CATEGORY_BONUSES: dict[str, float] = {
    "architectural_understanding": 1.0,
    "cross_file_refactoring": 0.9,
    "bug_investigation": 0.8,
    "security_analysis": 0.7,
    "feature_implementation": 0.5,
    "code_comprehension": 0.4,
    "integration_testing": 0.3,
    "multi_session_development": 0.3,
}

# Number of tasks to select
TOP_N = 50


def load_dataset(dataset_path: Path) -> list[dict[str, Any]]:
    """Load tasks from JSONL dataset file.

    Args:
        dataset_path: Path to the JSONL dataset file

    Returns:
        List of task dictionaries
    """
    tasks = []
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                tasks.append(json.loads(line))
    return tasks


def filter_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter tasks by minimum thresholds.

    Args:
        tasks: List of all tasks

    Returns:
        List of tasks meeting minimum criteria
    """
    filtered = []
    for task in tasks:
        context_length = task.get("context_length", 0)
        files_count = task.get("files_count", 0)

        if context_length > MIN_CONTEXT_LENGTH and files_count > MIN_FILES_COUNT:
            filtered.append(task)

    return filtered


def calculate_score(
    task: dict[str, Any],
    max_context_length: int,
    max_files_count: int,
) -> float:
    """Calculate composite score for a task.

    Score formula:
        score = (context_weight * context_score) +
                (files_weight * files_score) +
                (category_weight * category_bonus)

    Args:
        task: Task dictionary
        max_context_length: Maximum context length in dataset (for normalization)
        max_files_count: Maximum files count in dataset (for normalization)

    Returns:
        Composite score (0-1 scale)
    """
    context_length = task.get("context_length", 0)
    files_count = task.get("files_count", 0)
    task_category = task.get("task_category", "")

    # Normalize metrics (0-1 scale)
    context_score = context_length / max_context_length if max_context_length > 0 else 0
    files_score = files_count / max_files_count if max_files_count > 0 else 0

    # Get category bonus (default to 0.3 for unknown categories)
    category_bonus = CATEGORY_BONUSES.get(task_category, 0.3)

    # Calculate composite score
    score = (
        CONTEXT_WEIGHT * context_score
        + FILES_WEIGHT * files_score
        + CATEGORY_WEIGHT * category_bonus
    )

    return score


def score_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Score all tasks and add score field.

    Args:
        tasks: List of filtered tasks

    Returns:
        List of tasks with 'score' field added, sorted by score descending
    """
    if not tasks:
        return []

    # Find max values for normalization
    max_context_length = max(t.get("context_length", 0) for t in tasks)
    max_files_count = max(t.get("files_count", 0) for t in tasks)

    # Calculate scores
    scored_tasks = []
    for task in tasks:
        score = calculate_score(task, max_context_length, max_files_count)
        scored_task = task.copy()
        scored_task["score"] = round(score, 4)
        scored_tasks.append(scored_task)

    # Sort by score descending
    scored_tasks.sort(key=lambda t: t["score"], reverse=True)

    return scored_tasks


def print_selection_summary(
    original_count: int,
    filtered_count: int,
    selected_tasks: list[dict[str, Any]],
) -> None:
    """Print summary of selection process to stdout.

    Args:
        original_count: Total tasks in dataset
        filtered_count: Tasks after threshold filtering
        selected_tasks: Final selected tasks
    """
    print(f"\n=== Task Selection Summary ===")
    print(f"Total tasks in dataset: {original_count}")
    print(f"Tasks meeting thresholds: {filtered_count}")
    print(f"Tasks selected: {len(selected_tasks)}")

    if not selected_tasks:
        print("\nNo tasks selected!")
        return

    # Calculate statistics
    avg_context = sum(t["context_length"] for t in selected_tasks) / len(selected_tasks)
    avg_files = sum(t["files_count"] for t in selected_tasks) / len(selected_tasks)
    avg_score = sum(t["score"] for t in selected_tasks) / len(selected_tasks)

    print(f"\n=== Selection Statistics ===")
    print(f"Average context length: {avg_context:,.0f} tokens")
    print(f"Average files count: {avg_files:.1f}")
    print(f"Average score: {avg_score:.4f}")
    print(f"Score range: {selected_tasks[-1]['score']:.4f} - {selected_tasks[0]['score']:.4f}")

    # Category distribution
    categories: dict[str, int] = {}
    for task in selected_tasks:
        cat = task.get("task_category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1

    print(f"\n=== Category Distribution ===")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")

    # Language distribution
    languages: dict[str, int] = {}
    for task in selected_tasks:
        lang = task.get("language", "unknown")
        languages[lang] = languages.get(lang, 0) + 1

    print(f"\n=== Language Distribution ===")
    for lang, count in sorted(languages.items(), key=lambda x: -x[1]):
        print(f"  {lang}: {count}")

    # Top 10 tasks
    print(f"\n=== Top 10 Selected Tasks ===")
    for i, task in enumerate(selected_tasks[:10], 1):
        print(
            f"{i:2}. {task['id'][:60]:<60} "
            f"score={task['score']:.4f} "
            f"ctx={task['context_length']:,} "
            f"files={task['files_count']}"
        )


def main() -> int:
    """Main entry point for task selection."""
    # Determine paths relative to this script
    script_dir = Path(__file__).parent
    dataset_path = script_dir / "locobench_dataset.jsonl"
    output_path = script_dir / "selected_tasks.json"

    # Check dataset exists
    if not dataset_path.exists():
        print(f"Error: Dataset not found: {dataset_path}", file=sys.stderr)
        print("Run extract_dataset.py first to create the dataset.", file=sys.stderr)
        return 1

    # Load dataset
    print(f"Loading dataset from {dataset_path}")
    tasks = load_dataset(dataset_path)
    print(f"Loaded {len(tasks)} tasks")

    # Filter by thresholds
    print(f"\nApplying thresholds: context_length > {MIN_CONTEXT_LENGTH:,}, files_count > {MIN_FILES_COUNT}")
    filtered_tasks = filter_tasks(tasks)
    print(f"Tasks meeting thresholds: {len(filtered_tasks)}")

    # Score and rank
    print("\nScoring tasks...")
    scored_tasks = score_tasks(filtered_tasks)

    # Select top N
    selected_tasks = scored_tasks[:TOP_N]

    # Print summary
    print_selection_summary(len(tasks), len(filtered_tasks), selected_tasks)

    # Write output
    output_data = {
        "selection_criteria": {
            "min_context_length": MIN_CONTEXT_LENGTH,
            "min_files_count": MIN_FILES_COUNT,
            "context_weight": CONTEXT_WEIGHT,
            "files_weight": FILES_WEIGHT,
            "category_weight": CATEGORY_WEIGHT,
            "category_bonuses": CATEGORY_BONUSES,
            "top_n": TOP_N,
        },
        "statistics": {
            "total_tasks": len(tasks),
            "filtered_tasks": len(filtered_tasks),
            "selected_tasks": len(selected_tasks),
        },
        "tasks": selected_tasks,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)

    print(f"\nWrote {len(selected_tasks)} selected tasks to {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
