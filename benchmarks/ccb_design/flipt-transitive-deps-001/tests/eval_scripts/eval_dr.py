#!/usr/bin/env python3
"""DependEval DR (Dependency Recognition / file ordering) evaluation script.

Scores agent-produced file dependency ordering against DependEval Task 2
ground truth. The ground truth is a list of file paths in correct dependency
order (callees before callers).

Usage inside Harbor task container:
    python3 /tests/eval_scripts/dependeval_eval_dr.py

Expects:
    /workspace/submission.json  — JSON array of file paths in dependency order
    /tests/ground_truth.json    — JSON array of file paths (correct order)

Writes:
    /logs/verifier/reward.txt   — float reward in [0.0, 1.0]

Self-test:
    python3 scripts/dependeval_eval_dr.py --test
"""

from __future__ import annotations

import json
import os
import sys


def normalize_path(p: str) -> str:
    """Strip surrounding quotes and whitespace from a file path string."""
    return p.strip().strip("'\"")


def kendall_tau_normalized(submission: list[str], ground_truth: list[str]) -> float:
    """Compute normalized Kendall tau rank correlation between two orderings.

    Maps items in submission to their positions in ground_truth and counts
    concordant vs discordant pairs. Returns a score in [0.0, 1.0] where
    1.0 = identical ordering and 0.0 = maximally discordant.

    Items in submission not found in ground_truth are ignored.
    """
    gt_index = {item: i for i, item in enumerate(ground_truth)}
    # Map submission items to their ground-truth positions (skip unknowns)
    ranks = [gt_index[item] for item in submission if item in gt_index]

    n = len(ranks)
    if n < 2:
        return 0.0

    concordant = 0
    discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            if ranks[i] < ranks[j]:
                concordant += 1
            elif ranks[i] > ranks[j]:
                discordant += 1

    total_pairs = n * (n - 1) // 2
    if total_pairs == 0:
        return 0.0

    # Kendall tau in [-1, 1], normalize to [0, 1]
    tau = (concordant - discordant) / total_pairs
    return (tau + 1.0) / 2.0


def position_exact_match(submission: list[str], ground_truth: list[str]) -> float:
    """Score file ordering by element-wise exact match averaged across positions.

    If lengths differ, missing positions score 0.
    """
    if not ground_truth:
        return 0.0

    n = len(ground_truth)
    matches = 0
    for i in range(n):
        if i < len(submission) and submission[i] == ground_truth[i]:
            matches += 1

    return matches / n


def score_ordering(submission: list[str], ground_truth: list[str]) -> float:
    """Score file ordering using blended exact-match and rank-correlation.

    Combines position-exact-match (60%) with Kendall tau correlation (40%)
    to give partial credit for near-correct orderings.

    Both lists are normalized (stripped of surrounding quotes/whitespace).
    """
    if not ground_truth:
        return 0.0

    sub_norm = [normalize_path(p) for p in submission]
    gt_norm = [normalize_path(p) for p in ground_truth]

    exact = position_exact_match(sub_norm, gt_norm)
    tau = kendall_tau_normalized(sub_norm, gt_norm)

    return 0.6 * exact + 0.4 * tau


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
    """Run DR evaluation and write reward. Returns the reward."""
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

    reward = score_ordering(sub, gt)
    write_reward(reward, reward_path)
    print(f"DR reward: {reward:.4f} ({len(gt)} positions, "
          f"submission has {len(sub)} entries)")
    return reward


def run_self_test() -> None:
    """Run inline smoke tests."""
    print("Running DR eval self-tests...")

    # Test 1: Perfect match -> 0.6*1.0 + 0.4*1.0 = 1.0
    gt = ["'repo/a.py'", "'repo/b.py'", "'repo/c.py'"]
    sub = ["'repo/a.py'", "'repo/b.py'", "'repo/c.py'"]
    score = score_ordering(sub, gt)
    assert abs(score - 1.0) < 0.01, f"Test 1 failed: expected 1.0, got {score}"
    print(f"  [PASS] Test 1: Perfect match -> {score:.4f}")

    # Test 2: Completely wrong order [c,a,b] vs [a,b,c]
    # exact=0/3=0.0, tau: pairs (c,a)=disc, (c,b)=disc, (a,b)=conc -> tau=(1-2)/3=-1/3
    # normalized=(−1/3+1)/2=1/3 -> blended=0.6*0+0.4*(1/3)=0.133
    sub2 = ["'repo/c.py'", "'repo/a.py'", "'repo/b.py'"]
    score2 = score_ordering(sub2, gt)
    assert abs(score2 - 0.133) < 0.02, f"Test 2 failed: expected ~0.133, got {score2}"
    print(f"  [PASS] Test 2: Wrong order -> {score2:.4f}")

    # Test 3: Partial match [a,c,b] vs [a,b,c]
    # exact=1/3, tau: pairs (a,c)=conc, (a,b)=conc, (c,b)=disc -> tau=(2-1)/3=1/3
    # normalized=(1/3+1)/2=2/3 -> blended=0.6*(1/3)+0.4*(2/3)=0.2+0.267=0.467
    sub3 = ["'repo/a.py'", "'repo/c.py'", "'repo/b.py'"]
    score3 = score_ordering(sub3, gt)
    assert abs(score3 - 0.467) < 0.02, f"Test 3 failed: expected ~0.467, got {score3}"
    print(f"  [PASS] Test 3: Single swap -> {score3:.4f}")

    # Test 4: Empty submission -> 0.0
    score4 = score_ordering([], gt)
    assert score4 == 0.0, f"Test 4 failed: expected 0.0, got {score4}"
    print(f"  [PASS] Test 4: Empty submission -> {score4:.4f}")

    # Test 5: Empty ground truth -> 0.0
    score5 = score_ordering(["a.py"], [])
    assert score5 == 0.0, f"Test 5 failed: expected 0.0, got {score5}"
    print(f"  [PASS] Test 5: Empty ground truth -> {score5:.4f}")

    # Test 6: Path normalization (quotes stripped) -> 1.0
    gt6 = ["'repo/a.py'", "'repo/b.py'"]
    sub6 = ["repo/a.py", "repo/b.py"]
    score6 = score_ordering(sub6, gt6)
    assert abs(score6 - 1.0) < 0.01, f"Test 6 failed: expected 1.0, got {score6}"
    print(f"  [PASS] Test 6: Quote normalization -> {score6:.4f}")

    # Test 7: Submission shorter than ground truth [a,b] vs [a,b,c,d]
    # exact=2/4=0.5, tau on [a,b] = conc -> tau=1/1=1.0, normalized=1.0
    # blended=0.6*0.5+0.4*1.0=0.7
    gt7 = ["'a.py'", "'b.py'", "'c.py'", "'d.py'"]
    sub7 = ["'a.py'", "'b.py'"]
    score7 = score_ordering(sub7, gt7)
    assert abs(score7 - 0.7) < 0.02, f"Test 7 failed: expected ~0.7, got {score7}"
    print(f"  [PASS] Test 7: Short submission -> {score7:.4f}")

    # Test 8: Submission longer than ground truth (exact prefix) -> 1.0
    sub8 = ["'a.py'", "'b.py'", "'c.py'", "'d.py'", "'e.py'"]
    score8 = score_ordering(sub8, gt7)
    assert abs(score8 - 1.0) < 0.01, f"Test 8 failed: expected 1.0, got {score8}"
    print(f"  [PASS] Test 8: Long submission (exact prefix) -> {score8:.4f}")

    # Test 9: Reverse order [d,c,b,a] vs [a,b,c,d]
    # exact=0/4=0.0, tau: all 6 pairs discordant -> tau=-1.0, normalized=0.0
    # blended=0.6*0+0.4*0=0.0
    sub9 = ["'d.py'", "'c.py'", "'b.py'", "'a.py'"]
    score9 = score_ordering(sub9, gt7)
    assert abs(score9 - 0.0) < 0.01, f"Test 9 failed: expected 0.0, got {score9}"
    print(f"  [PASS] Test 9: Reverse order -> {score9:.4f}")

    print("All DR eval self-tests passed!")


if __name__ == "__main__":
    if "--test" in sys.argv:
        run_self_test()
        sys.exit(0)

    evaluate()
