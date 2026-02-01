#!/usr/bin/env python3
"""
AINativeBench Verifier

Parses AINativeBench's native test_results/ JSON output and converts
it to Harbor's reward.json format.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def parse_test_results(test_results_dir: Path) -> dict[str, Any]:
    """
    Parse test results from AINativeBench's native output format.

    AINativeBench stores test results as JSON files in test_results/ directory.

    Args:
        test_results_dir: Path to test_results directory.

    Returns:
        Aggregated test results.
    """
    results: dict[str, Any] = {
        "total_tests": 0,
        "passed_tests": 0,
        "failed_tests": 0,
        "test_details": [],
    }

    if not test_results_dir.exists():
        return results

    # Find all JSON result files
    json_files = list(test_results_dir.glob("*.json"))

    for json_file in json_files:
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                test_result = json.load(f)

            results["total_tests"] += 1

            # Check for pass/fail status
            # AINativeBench uses various status indicators
            passed = False
            if isinstance(test_result, dict):
                # Check common status fields
                if test_result.get("passed", False):
                    passed = True
                elif test_result.get("status") == "passed":
                    passed = True
                elif test_result.get("result") == "pass":
                    passed = True
                elif test_result.get("success", False):
                    passed = True

            if passed:
                results["passed_tests"] += 1
            else:
                results["failed_tests"] += 1

            results["test_details"].append({
                "file": json_file.name,
                "passed": passed,
                "data": test_result,
            })

        except (json.JSONDecodeError, IOError) as e:
            results["test_details"].append({
                "file": json_file.name,
                "passed": False,
                "error": str(e),
            })
            results["total_tests"] += 1
            results["failed_tests"] += 1

    return results


def compute_score(
    test_results: dict[str, Any],
    ground_truth: dict[str, Any],
) -> dict[str, Any]:
    """
    Compute the final score based on test results and ground truth.

    Args:
        test_results: Parsed test results.
        ground_truth: Ground truth data including scoring metrics.

    Returns:
        Score dictionary in Harbor reward.json format.
    """
    total = test_results["total_tests"]
    passed = test_results["passed_tests"]

    # Compute pass rate
    if total > 0:
        pass_rate = passed / total
    else:
        pass_rate = 0.0

    # Get scoring metrics from ground truth
    scoring_metrics = ground_truth.get("scoring_metrics", {})
    primary_metric = scoring_metrics.get("primary_metric", "pass_rate")

    # Build reward result
    result: dict[str, Any] = {
        "score": round(pass_rate, 4),
        "metrics": {
            "pass_rate": round(pass_rate, 4),
            "total_tests": total,
            "passed_tests": passed,
            "failed_tests": test_results["failed_tests"],
        },
        "primary_metric": primary_metric,
        "test_details": test_results["test_details"],
    }

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="AINativeBench Verifier")
    parser.add_argument(
        "--test-results-dir",
        required=True,
        help="Path to test_results directory",
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

    test_results_dir = Path(args.test_results_dir)
    ground_truth_path = Path(args.ground_truth)
    output_path = Path(args.output)

    # Read ground truth
    if not ground_truth_path.exists():
        error_result: dict[str, Any] = {"score": 0.0, "error": f"Ground truth not found: {ground_truth_path}"}
        output_path.write_text(json.dumps(error_result, indent=2))
        print(f"Error: {error_result['error']}")
        return

    with open(ground_truth_path, "r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    # Parse test results
    test_results = parse_test_results(test_results_dir)

    result: dict[str, Any]
    if test_results["total_tests"] == 0:
        # No test results found - check if this is expected
        print("Warning: No test results found in test_results directory")
        result = {
            "score": 0.0,
            "metrics": {
                "pass_rate": 0.0,
                "total_tests": 0,
                "passed_tests": 0,
                "failed_tests": 0,
            },
            "error": "No test results found",
        }
    else:
        # Compute score
        result = compute_score(test_results, ground_truth)

    # Write output
    output_path.write_text(json.dumps(result, indent=2))

    print("Evaluation complete:")
    print(f"  Score: {result['score']}")
    metrics = result.get("metrics")
    if metrics is not None and isinstance(metrics, dict):
        print(f"  Pass rate: {metrics.get('pass_rate', 'N/A')}")
        print(f"  Tests: {metrics.get('passed_tests', 0)}/{metrics.get('total_tests', 0)}")


if __name__ == "__main__":
    main()
