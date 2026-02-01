#!/usr/bin/env python3
"""
SWE-Perf Verifier

Evaluates agent output by measuring runtime reduction compared to baseline.
The primary metric is runtime_reduction = 1 - (optimized_runtime / baseline_runtime).
"""

import argparse
import json
from pathlib import Path
from typing import Any


def evaluate_runtime(
    benchmark_results: dict[str, Any] | None,
    ground_truth: dict[str, Any],
) -> dict[str, Any]:
    """
    Evaluate runtime reduction from benchmark results.

    Args:
        benchmark_results: Benchmark results from agent or verifier.
        ground_truth: Ground truth with baseline runtime.

    Returns:
        Evaluation result dictionary with runtime_reduction as primary metric.
    """
    baseline_runtime = ground_truth.get("baseline_runtime", 0.0)

    if baseline_runtime <= 0:
        return {
            "score": 0.0,
            "runtime_reduction": 0.0,
            "error": "Invalid baseline runtime",
            "metrics": {},
        }

    # If no benchmark results provided, check for agent-provided results
    if benchmark_results is None:
        return {
            "score": 0.0,
            "runtime_reduction": 0.0,
            "note": "No benchmark results provided",
            "metrics": {
                "baseline_runtime": baseline_runtime,
                "optimized_runtime": None,
            },
        }

    # Get optimized runtime from results
    optimized_runtime = benchmark_results.get(
        "optimized_runtime",
        benchmark_results.get("runtime", benchmark_results.get("mean_time")),
    )

    # Check if tests passed (correctness check)
    tests_passed = benchmark_results.get("tests_passed", True)
    if isinstance(tests_passed, int):
        tests_total = benchmark_results.get("tests_total", tests_passed)
        tests_passed = tests_passed >= tests_total if tests_total > 0 else True

    if not tests_passed:
        return {
            "score": 0.0,
            "runtime_reduction": 0.0,
            "error": "Tests failed - correctness not verified",
            "metrics": {
                "baseline_runtime": baseline_runtime,
                "optimized_runtime": optimized_runtime,
                "tests_passed": False,
            },
        }

    if optimized_runtime is None:
        return {
            "score": 0.0,
            "runtime_reduction": 0.0,
            "note": "No optimized runtime in benchmark results",
            "metrics": {
                "baseline_runtime": baseline_runtime,
            },
        }

    # Compute runtime reduction
    # runtime_reduction = 1 - (optimized / baseline)
    # 0.0 = no improvement, 0.5 = 2x speedup, 0.9 = 10x speedup
    if optimized_runtime <= 0:
        runtime_reduction = 0.0
    else:
        runtime_reduction = 1.0 - (optimized_runtime / baseline_runtime)

    # Clamp to valid range [0, 1]
    runtime_reduction = max(0.0, min(1.0, runtime_reduction))

    # Use runtime_reduction as the score
    score = runtime_reduction

    # Calculate speedup factor for informational purposes
    speedup = baseline_runtime / optimized_runtime if optimized_runtime > 0 else 0.0

    return {
        "score": round(score, 4),
        "runtime_reduction": round(runtime_reduction, 4),
        "metrics": {
            "baseline_runtime": baseline_runtime,
            "optimized_runtime": optimized_runtime,
            "speedup": round(speedup, 2),
            "tests_passed": tests_passed,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="SWE-Perf Verifier")
    parser.add_argument(
        "--optimized-dir",
        help="Path to optimized code directory",
    )
    parser.add_argument(
        "--benchmark-results",
        help="Path to benchmark results JSON (optional)",
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

    # Read benchmark results if provided
    benchmark_results = None
    if args.benchmark_results and args.benchmark_results != "":
        benchmark_path = Path(args.benchmark_results)
        if benchmark_path.exists():
            try:
                with open(benchmark_path, "r", encoding="utf-8") as f:
                    benchmark_results = json.load(f)
            except json.JSONDecodeError as e:
                print(f"Warning: Failed to parse benchmark results: {e}")

    # Evaluate
    result = evaluate_runtime(benchmark_results, ground_truth)

    # Write output
    output_path.write_text(json.dumps(result, indent=2))

    print("Evaluation complete:")
    print(f"  Score: {result.get('score', 0.0)}")
    print(f"  Runtime Reduction: {result.get('runtime_reduction', 0.0)}")
    metrics_val = result.get("metrics")
    metrics: dict[str, Any] = metrics_val if isinstance(metrics_val, dict) else {}
    if metrics:
        print(f"  Baseline: {metrics.get('baseline_runtime', 'N/A')}s")
        print(f"  Optimized: {metrics.get('optimized_runtime', 'N/A')}s")
        print(f"  Speedup: {metrics.get('speedup', 'N/A')}x")


if __name__ == "__main__":
    main()
