#!/usr/bin/env python3
"""Impact analysis evaluation script.

Scores agent-produced file discovery list against ground truth using F1 measure
(harmonic mean of precision and recall).

Usage inside Harbor task container:
    python3 /tests/eval_scripts/eval_impact.py

Expects:
    /workspace/submission.json  -- JSON array of file paths (discovered files)
    /tests/ground_truth.json    -- JSON array of file paths (correct answer)

Writes:
    /logs/verifier/reward.txt   -- float reward in [0.0, 1.0]

Self-test:
    python3 eval_impact.py --test
"""

from __future__ import annotations

import json
import os
import sys


def normalize_path(p: str) -> str:
    """Normalize a file path for comparison."""
    return p.strip().strip("'\"").strip("/")


def f1_score(submission: list[str], ground_truth: list[str]) -> float:
    """Compute F1 score between submission and ground truth file sets.

    F1 = 2 * precision * recall / (precision + recall)

    Both lists are normalized (stripped of surrounding quotes/whitespace/slashes).
    """
    if not ground_truth:
        return 0.0

    sub_set = {normalize_path(p) for p in submission}
    gt_set = {normalize_path(p) for p in ground_truth}

    if not sub_set:
        return 0.0

    true_positives = len(sub_set & gt_set)

    if true_positives == 0:
        return 0.0

    precision = true_positives / len(sub_set)
    recall = true_positives / len(gt_set)

    return 2 * precision * recall / (precision + recall)


def load_json(path: str) -> object:
    """Load a JSON file, returning None on any error."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def write_reward(reward: float, reward_path: str) -> None:
    """Write reward float to the reward file."""
    os.makedirs(os.path.dirname(reward_path), exist_ok=True)
    with open(reward_path, "w") as f:
        f.write(str(reward))


def evaluate(
    submission_path: str = "/workspace/submission.json",
    ground_truth_path: str = "/tests/ground_truth.json",
    reward_path: str = "/logs/verifier/reward.txt",
) -> float:
    """Run impact analysis evaluation and write reward. Returns the reward."""
    # Load ground truth
    gt = load_json(ground_truth_path)
    if not isinstance(gt, list):
        print(f"ERROR: Ground truth at {ground_truth_path} is not a JSON array",
              file=sys.stderr)
        write_reward(0.0, reward_path)
        return 0.0

    # Load submission
    sub = load_json(submission_path)
    if sub is None:
        print(f"WARNING: No valid submission at {submission_path}, reward=0.0",
              file=sys.stderr)
        write_reward(0.0, reward_path)
        return 0.0

    if not isinstance(sub, list):
        print(f"WARNING: Submission is not a JSON array, reward=0.0",
              file=sys.stderr)
        write_reward(0.0, reward_path)
        return 0.0

    reward = f1_score(sub, gt)

    # Print detailed breakdown
    sub_set = {normalize_path(p) for p in sub}
    gt_set = {normalize_path(p) for p in gt}
    tp = sub_set & gt_set
    fp = sub_set - gt_set
    fn = gt_set - sub_set

    print(f"Impact analysis reward: {reward:.4f}")
    print(f"  Ground truth: {len(gt_set)} files")
    print(f"  Submission:   {len(sub_set)} files")
    print(f"  True positives:  {len(tp)}")
    print(f"  False positives: {len(fp)}")
    print(f"  False negatives: {len(fn)}")
    if fp:
        print(f"  Extra files: {sorted(fp)}")
    if fn:
        print(f"  Missing files: {sorted(fn)}")

    write_reward(reward, reward_path)
    return reward


def run_self_test() -> None:
    """Run inline smoke tests."""
    print("Running impact analysis eval self-tests...")

    # Test 1: Perfect match -> 1.0
    gt = ["a.py", "b.py", "c.py"]
    sub = ["a.py", "b.py", "c.py"]
    score = f1_score(sub, gt)
    assert abs(score - 1.0) < 0.01, f"Test 1 failed: expected 1.0, got {score}"
    print(f"  [PASS] Test 1: Perfect match -> {score:.4f}")

    # Test 2: Empty submission -> 0.0
    score2 = f1_score([], gt)
    assert score2 == 0.0, f"Test 2 failed: expected 0.0, got {score2}"
    print(f"  [PASS] Test 2: Empty submission -> {score2:.4f}")

    # Test 3: Empty ground truth -> 0.0
    score3 = f1_score(["a.py"], [])
    assert score3 == 0.0, f"Test 3 failed: expected 0.0, got {score3}"
    print(f"  [PASS] Test 3: Empty ground truth -> {score3:.4f}")

    # Test 4: Partial overlap (2/3 recall, 2/2 precision)
    # F1 = 2 * 1.0 * 0.667 / (1.0 + 0.667) = 0.8
    sub4 = ["a.py", "b.py"]
    score4 = f1_score(sub4, gt)
    assert abs(score4 - 0.8) < 0.01, f"Test 4 failed: expected 0.8, got {score4}"
    print(f"  [PASS] Test 4: Missing one -> {score4:.4f}")

    # Test 5: With false positives (3/3 recall, 3/5 precision)
    # F1 = 2 * 0.6 * 1.0 / (0.6 + 1.0) = 0.75
    sub5 = ["a.py", "b.py", "c.py", "d.py", "e.py"]
    score5 = f1_score(sub5, gt)
    assert abs(score5 - 0.75) < 0.01, f"Test 5 failed: expected 0.75, got {score5}"
    print(f"  [PASS] Test 5: Extra files -> {score5:.4f}")

    # Test 6: No overlap -> 0.0
    sub6 = ["x.py", "y.py"]
    score6 = f1_score(sub6, gt)
    assert score6 == 0.0, f"Test 6 failed: expected 0.0, got {score6}"
    print(f"  [PASS] Test 6: No overlap -> {score6:.4f}")

    # Test 7: Path normalization (leading slash, quotes)
    gt7 = ["django/admin/options.py", "tests/test.py"]
    sub7 = ["/django/admin/options.py", "'tests/test.py'"]
    score7 = f1_score(sub7, gt7)
    assert abs(score7 - 1.0) < 0.01, f"Test 7 failed: expected 1.0, got {score7}"
    print(f"  [PASS] Test 7: Path normalization -> {score7:.4f}")

    print("All impact analysis eval self-tests passed!")


if __name__ == "__main__":
    if "--test" in sys.argv:
        run_self_test()
        sys.exit(0)

    evaluate()
