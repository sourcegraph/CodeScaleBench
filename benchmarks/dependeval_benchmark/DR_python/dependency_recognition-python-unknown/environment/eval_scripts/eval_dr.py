#!/usr/bin/env python3
"""
Dependency Recognition Evaluation Script

Evaluates exact match between predicted and ground truth dependencies.
Based on DependEval's eval_DR.py implementation.
"""

import argparse
import json
import re
import sys
from pathlib import Path


def extract_list_from_text(text: str) -> list | None:
    """Extract list from text using regex pattern matching"""
    if isinstance(text, list):
        return text

    # Try to extract [...] pattern
    match = re.search(r'\[.*?\]', str(text), re.DOTALL)
    if match:
        try:
            return eval(match.group(0))
        except:
            return None

    return None


def calculate_exact_match(pred: list, gt: list) -> float:
    """
    Calculate exact match score

    Returns 1.0 if all items match exactly, 0.0 otherwise
    """
    if not isinstance(pred, list) or not isinstance(gt, list):
        return 0.0

    # Convert to sets for comparison (order-independent)
    pred_set = set(str(x) for x in pred)
    gt_set = set(str(x) for x in gt)

    if len(pred_set) == 0 and len(gt_set) == 0:
        return 1.0

    if pred_set == gt_set:
        return 1.0

    return 0.0


def evaluate_dr(prediction_file: Path, ground_truth_file: Path) -> float:
    """
    Evaluate Dependency Recognition task

    Returns:
        Score between 0.0 and 1.0
    """
    try:
        # Load prediction
        with open(prediction_file) as f:
            pred_data = json.load(f)

        # Load ground truth
        with open(ground_truth_file) as f:
            gt_data = json.load(f)

        # Extract lists
        pred_list = extract_list_from_text(pred_data)
        gt_list = extract_list_from_text(gt_data)

        if pred_list is None:
            print(f"Warning: Could not parse prediction as list", file=sys.stderr)
            return 0.0

        if gt_list is None:
            print(f"Warning: Could not parse ground truth as list", file=sys.stderr)
            return 0.0

        # Calculate exact match
        score = calculate_exact_match(pred_list, gt_list)

        return score

    except Exception as e:
        print(f"Error during evaluation: {e}", file=sys.stderr)
        return 0.0


def main():
    parser = argparse.ArgumentParser(description="Evaluate Dependency Recognition")
    parser.add_argument("--prediction", required=True, help="Path to prediction file")
    parser.add_argument("--ground_truth", required=True, help="Path to ground truth file")
    parser.add_argument("--output", required=True, help="Path to output reward file")

    args = parser.parse_args()

    # Run evaluation
    score = evaluate_dr(
        Path(args.prediction),
        Path(args.ground_truth)
    )

    # Write reward
    with open(args.output, 'w') as f:
        f.write(f"{score:.4f}\n")

    print(f"Dependency Recognition Score: {score:.4f}")


if __name__ == "__main__":
    main()
