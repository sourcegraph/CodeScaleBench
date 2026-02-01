#!/usr/bin/env python3
"""
Multi-file Editing Evaluation Script

Simplified evaluation for multi-file editing tasks.
Note: The original DependEval uses LLM-based evaluation, which requires API access.
This version uses a simpler string similarity-based approach.
"""

import argparse
import json
import sys
from pathlib import Path
from difflib import SequenceMatcher


def normalize_code(code: str) -> str:
    """Normalize code for comparison"""
    # Remove extra whitespace
    lines = [line.strip() for line in code.split('\n')]
    # Remove empty lines
    lines = [line for line in lines if line]
    return '\n'.join(lines)


def calculate_similarity(pred: str, gt: str) -> float:
    """Calculate similarity between predicted and ground truth code"""
    pred_norm = normalize_code(pred)
    gt_norm = normalize_code(gt)

    # Use sequence matcher for similarity
    matcher = SequenceMatcher(None, pred_norm, gt_norm)
    return matcher.ratio()


def evaluate_me(prediction_file: Path, ground_truth_file: Path) -> float:
    """
    Evaluate Multi-file Editing task

    Returns:
        Score between 0.0 and 1.0

    Note: This is a simplified version. The original DependEval implementation
    uses LLM-based evaluation across 5 dimensions:
    1. Function Call Correctness (25%)
    2. Feature Alignment (25%)
    3. Implementation Accuracy (20%)
    4. Completeness (20%)
    5. Code Quality (10%)

    This version uses simple string similarity as a proxy.
    """
    try:
        # Load prediction
        with open(prediction_file) as f:
            pred_data = json.load(f)

        # Load ground truth
        with open(ground_truth_file) as f:
            gt_data = json.load(f)

        # Handle different formats
        if isinstance(pred_data, dict) and isinstance(gt_data, dict):
            # File-based format: {filename: content}
            total_similarity = 0.0
            file_count = 0

            for filename in gt_data:
                if filename in pred_data:
                    pred_content = str(pred_data[filename])
                    gt_content = str(gt_data[filename])
                    similarity = calculate_similarity(pred_content, gt_content)
                    total_similarity += similarity
                    file_count += 1
                else:
                    # Missing file
                    file_count += 1

            if file_count == 0:
                return 0.0

            score = total_similarity / file_count

        elif isinstance(pred_data, str) and isinstance(gt_data, str):
            # Single string format
            score = calculate_similarity(pred_data, gt_data)

        else:
            # Try converting to strings
            pred_str = json.dumps(pred_data, sort_keys=True, indent=2)
            gt_str = json.dumps(gt_data, sort_keys=True, indent=2)
            score = calculate_similarity(pred_str, gt_str)

        return score

    except Exception as e:
        print(f"Error during evaluation: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 0.0


def main():
    parser = argparse.ArgumentParser(description="Evaluate Multi-file Editing")
    parser.add_argument("--prediction", required=True, help="Path to prediction file")
    parser.add_argument("--ground_truth", required=True, help="Path to ground truth file")
    parser.add_argument("--output", required=True, help="Path to output reward file")

    args = parser.parse_args()

    # Run evaluation
    score = evaluate_me(
        Path(args.prediction),
        Path(args.ground_truth)
    )

    # Write reward
    with open(args.output, 'w') as f:
        f.write(f"{score:.4f}\n")

    print(f"Multi-file Editing Score: {score:.4f}")


if __name__ == "__main__":
    main()
