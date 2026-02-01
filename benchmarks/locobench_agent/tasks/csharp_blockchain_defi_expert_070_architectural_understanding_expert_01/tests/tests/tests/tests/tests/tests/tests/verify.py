#!/usr/bin/env python3
"""
LoCoBench-Agent Solution Verifier

Evaluates agent solutions against ground truth using keyword matching
and structural analysis. For more sophisticated evaluation, this can
be extended to use LLM-based semantic similarity.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    # Convert to lowercase
    text = text.lower()
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text)
    # Remove punctuation
    text = re.sub(r'[^\w\s]', '', text)
    return text.strip()


def extract_keywords(text: str) -> set[str]:
    """Extract meaningful keywords from text."""
    # Common stop words to ignore
    stop_words = {
        'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
        'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
        'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare',
        'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from', 'as',
        'into', 'through', 'during', 'before', 'after', 'above', 'below',
        'between', 'under', 'again', 'further', 'then', 'once', 'here',
        'there', 'when', 'where', 'why', 'how', 'all', 'each', 'few', 'more',
        'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own',
        'same', 'so', 'than', 'too', 'very', 'just', 'and', 'but', 'if', 'or',
        'because', 'until', 'while', 'this', 'that', 'these', 'those', 'it',
        'its', 'you', 'your', 'they', 'them', 'their', 'we', 'our', 'i', 'me',
    }

    normalized = normalize_text(text)
    words = set(normalized.split())
    # Filter out stop words and short words
    keywords = {w for w in words if w not in stop_words and len(w) > 2}
    return keywords


def compute_keyword_overlap(solution: str, ground_truth: str) -> float:
    """Compute keyword overlap score between solution and ground truth."""
    solution_keywords = extract_keywords(solution)
    truth_keywords = extract_keywords(ground_truth)

    if not truth_keywords:
        return 0.0

    overlap = solution_keywords & truth_keywords
    # Use F1-like score combining precision and recall
    precision = len(overlap) / len(solution_keywords) if solution_keywords else 0.0
    recall = len(overlap) / len(truth_keywords)

    if precision + recall == 0:
        return 0.0

    f1 = 2 * (precision * recall) / (precision + recall)
    return f1


def check_file_references(solution: str, context_files: list[str]) -> float:
    """Check if solution references relevant files from context."""
    if not context_files:
        return 1.0  # No files to check

    # Normalize file paths (convert // to /)
    normalized_files = [f.replace('//', '/') for f in context_files]

    # Count file references in solution
    referenced = 0
    for filepath in normalized_files:
        # Check for full path or filename
        filename = Path(filepath).name
        if filepath in solution or filename in solution:
            referenced += 1

    # Return ratio of referenced files (with min threshold)
    ratio = referenced / len(normalized_files)
    # Cap at 1.0 and give partial credit
    return min(ratio * 2, 1.0)


def check_code_blocks(solution: str) -> float:
    """Check if solution contains code blocks (when appropriate)."""
    # Look for markdown code blocks
    code_blocks = re.findall(r'```[\w]*\n[\s\S]*?```', solution)

    # Having code blocks is a good sign for implementation tasks
    if code_blocks:
        return 1.0

    # Check for inline code
    inline_code = re.findall(r'`[^`]+`', solution)
    if inline_code:
        return 0.5

    return 0.0


def evaluate_solution(
    solution_text: str,
    ground_truth: dict[str, Any] | str,
    context_files: list[str] | None = None,
) -> dict[str, Any]:
    """
    Evaluate solution against ground truth.

    Returns a dictionary with score (0.0-1.0) and detailed metrics.
    """
    # Handle ground_truth as string or dict
    if isinstance(ground_truth, dict):
        truth_text = json.dumps(ground_truth)
    else:
        truth_text = str(ground_truth)

    # Compute component scores
    keyword_score = compute_keyword_overlap(solution_text, truth_text)
    file_ref_score = check_file_references(solution_text, context_files or [])
    code_block_score = check_code_blocks(solution_text)

    # Check solution length (penalize very short solutions)
    solution_len = len(solution_text.split())
    length_score = min(solution_len / 100, 1.0)  # Full credit at 100+ words

    # Weighted combination
    # Keyword overlap is most important for semantic similarity
    # File references show the agent explored the codebase
    # Code blocks show implementation effort
    # Length is a basic sanity check
    final_score = (
        0.5 * keyword_score +
        0.2 * file_ref_score +
        0.2 * code_block_score +
        0.1 * length_score
    )

    return {
        "score": round(final_score, 4),
        "metrics": {
            "keyword_overlap": round(keyword_score, 4),
            "file_references": round(file_ref_score, 4),
            "code_blocks": round(code_block_score, 4),
            "length_score": round(length_score, 4),
        },
        "solution_words": solution_len,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="LoCoBench-Agent Solution Verifier")
    parser.add_argument("--solution", required=True, help="Path to solution file")
    parser.add_argument("--ground-truth", required=True, help="Path to ground truth JSON")
    parser.add_argument("--output", required=True, help="Path to output reward JSON")
    args = parser.parse_args()

    # Read solution
    solution_path = Path(args.solution)
    if not solution_path.exists():
        result = {"score": 0.0, "error": f"Solution file not found: {args.solution}"}
        Path(args.output).write_text(json.dumps(result, indent=2))
        print(f"Error: {result['error']}")
        return

    solution_text = solution_path.read_text()

    # Read ground truth
    truth_path = Path(args.ground_truth)
    if not truth_path.exists():
        result = {"score": 0.0, "error": f"Ground truth not found: {args.ground_truth}"}
        Path(args.output).write_text(json.dumps(result, indent=2))
        print(f"Error: {result['error']}")
        return

    ground_truth_data = json.loads(truth_path.read_text())

    # Extract ground truth and context files
    ground_truth = ground_truth_data.get("ground_truth", ground_truth_data)
    context_files = ground_truth_data.get("context_files", [])

    # Evaluate
    result = evaluate_solution(solution_text, ground_truth, context_files)

    # Write output
    Path(args.output).write_text(json.dumps(result, indent=2))

    print(f"Evaluation complete:")
    print(f"  Score: {result['score']}")
    print(f"  Metrics: {result['metrics']}")


if __name__ == "__main__":
    main()
