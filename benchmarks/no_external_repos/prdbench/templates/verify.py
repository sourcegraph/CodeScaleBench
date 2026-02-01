#!/usr/bin/env python3
"""
PRDBench Verifier

Evaluates agent output against evaluation criteria from the test plan.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def evaluate_criteria(
    test_results: dict[str, Any] | None,
    ground_truth: dict[str, Any],
) -> dict[str, Any]:
    """
    Evaluate test results against evaluation criteria.

    Args:
        test_results: Test results from the agent (may be None if no results).
        ground_truth: Ground truth with evaluation criteria.

    Returns:
        Evaluation result dictionary.
    """
    criteria = ground_truth.get("evaluation_criteria", [])
    total_criteria = len(criteria)

    if total_criteria == 0:
        return {
            "score": 0.0,
            "metrics": {
                "total_criteria": 0,
                "passed_criteria": 0,
            },
            "note": "No evaluation criteria defined",
        }

    if test_results is None:
        return {
            "score": 0.0,
            "metrics": {
                "total_criteria": total_criteria,
                "passed_criteria": 0,
                "criteria_results": {},
            },
            "note": "No test results provided",
        }

    # Extract criterion results from test results
    criterion_results = test_results.get("criteria_results", {})

    # Alternative: check for test pass/fail counts
    tests_passed = test_results.get("tests_passed", 0)
    tests_total = test_results.get("tests_total", 0)

    # Calculate score based on criteria
    passed_count = 0
    total_weight = 0.0
    weighted_score = 0.0
    criteria_scores: dict[str, dict[str, Any]] = {}

    for crit in criteria:
        crit_id = crit.get("id", "")
        crit_weight = crit.get("weight", 1.0)
        total_weight += crit_weight

        # Check if criterion passed
        passed = False
        if crit_id in criterion_results:
            result = criterion_results[crit_id]
            if isinstance(result, bool):
                passed = result
            elif isinstance(result, dict):
                passed = result.get("passed", False)

        if passed:
            passed_count += 1
            weighted_score += crit_weight

        criteria_scores[crit_id] = {
            "name": crit.get("name", ""),
            "passed": passed,
            "weight": crit_weight,
        }

    # Compute final score
    if total_weight > 0:
        score = weighted_score / total_weight
    elif total_criteria > 0:
        score = passed_count / total_criteria
    else:
        score = 0.0

    return {
        "score": round(score, 4),
        "metrics": {
            "total_criteria": total_criteria,
            "passed_criteria": passed_count,
            "total_weight": total_weight,
            "weighted_score": weighted_score,
            "criteria_scores": criteria_scores,
            "tests_passed": tests_passed,
            "tests_total": tests_total,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="PRDBench Verifier")
    parser.add_argument(
        "--test-results",
        help="Path to test results JSON file (optional)",
    )
    parser.add_argument(
        "--ground-truth",
        required=True,
        help="Path to ground truth JSON",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to output reward JSON",
    )
    args = parser.parse_args()

    ground_truth_path = Path(args.ground_truth)
    output_path = Path(args.output)

    # Read ground truth
    if not ground_truth_path.exists():
        result = {"score": 0.0, "error": f"Ground truth not found: {ground_truth_path}"}
        output_path.write_text(json.dumps(result, indent=2))
        print(f"Error: {result['error']}")
        return

    with open(ground_truth_path, "r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    # Read test results if provided
    test_results = None
    if args.test_results and args.test_results != "":
        test_results_path = Path(args.test_results)
        if test_results_path.exists():
            try:
                with open(test_results_path, "r", encoding="utf-8") as f:
                    test_results = json.load(f)
            except json.JSONDecodeError as e:
                print(f"Warning: Failed to parse test results: {e}")

    # Evaluate
    result = evaluate_criteria(test_results, ground_truth)

    # Write output
    output_path.write_text(json.dumps(result, indent=2))

    print(f"Evaluation complete:")
    print(f"  Score: {result.get('score', 0.0)}")
    metrics = result.get("metrics", {})
    print(f"  Criteria: {metrics.get('passed_criteria', 0)}/{metrics.get('total_criteria', 0)}")


if __name__ == "__main__":
    main()
