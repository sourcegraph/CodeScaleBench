#!/usr/bin/env python3
"""Diff-based verifier for PyTorch benchmark tasks.

Compares the agent's changes against a pre-computed ground truth diff.
Outputs a reward.json with a 3-component score.

Scoring:
  - file_recall (0.35): fraction of expected files the agent touched
  - line_recall (0.45): fraction of expected diff lines matched
  - line_precision (0.20): fraction of agent diff lines in expected diff

Gate: if agent made no changes vs pre_fix_rev, reward = 0.0.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict


def normalize_line(line: str) -> str:
    """Normalize a diff line for fuzzy matching.

    Strips leading/trailing whitespace, collapses internal whitespace.
    Returns empty string for blank/whitespace-only lines.
    """
    stripped = line.strip()
    if not stripped:
        return ""
    return re.sub(r"\s+", " ", stripped)


def parse_unified_diff(text: str) -> dict:
    """Parse a unified diff into per-file added/removed lines.

    Returns dict mapping filename -> {"added": [str], "removed": [str]}
    where each line is normalized.
    """
    files = defaultdict(lambda: {"added": [], "removed": []})
    current_file = None

    for raw_line in text.splitlines():
        # Detect file header: +++ b/path/to/file
        if raw_line.startswith("+++ b/"):
            current_file = raw_line[6:].strip()
            continue
        if raw_line.startswith("--- a/") or raw_line.startswith("--- /dev/null"):
            continue
        if raw_line.startswith("@@"):
            continue
        if raw_line.startswith("diff --git"):
            continue

        if current_file is None:
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            normed = normalize_line(raw_line[1:])
            if normed:
                files[current_file]["added"].append(normed)
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            normed = normalize_line(raw_line[1:])
            if normed:
                files[current_file]["removed"].append(normed)

    return dict(files)


def compute_scores(expected: dict, actual: dict) -> dict:
    """Compute the 3-component score.

    Args:
        expected: parsed ground truth diff {file: {added: [], removed: []}}
        actual: parsed agent diff {file: {added: [], removed: []}}

    Returns:
        dict with file_recall, line_recall, line_precision, reward
    """
    expected_files = set(expected.keys())
    actual_files = set(actual.keys())

    # File recall
    if not expected_files:
        file_recall = 0.0
    else:
        file_recall = len(expected_files & actual_files) / len(expected_files)

    # Collect all expected and actual lines (per-file matching)
    expected_lines_total = 0
    matched_expected = 0
    actual_lines_total = 0
    matched_actual = 0

    for fname in expected_files | actual_files:
        exp_added = expected.get(fname, {}).get("added", [])
        exp_removed = expected.get(fname, {}).get("removed", [])
        act_added = actual.get(fname, {}).get("added", [])
        act_removed = actual.get(fname, {}).get("removed", [])

        exp_lines = exp_added + exp_removed
        act_lines = act_added + act_removed

        expected_lines_total += len(exp_lines)
        actual_lines_total += len(act_lines)

        # Use multiset matching: each expected line can match at most one actual line
        act_pool = list(act_lines)
        for eline in exp_lines:
            if eline in act_pool:
                matched_expected += 1
                act_pool.remove(eline)

        # For precision: each actual line can match at most one expected line
        exp_pool = list(exp_lines)
        for aline in act_lines:
            if aline in exp_pool:
                matched_actual += 1
                exp_pool.remove(aline)

    # Line recall
    if expected_lines_total == 0:
        line_recall = 0.0
    else:
        line_recall = matched_expected / expected_lines_total

    # Line precision
    if actual_lines_total == 0:
        line_precision = 0.0
    else:
        line_precision = matched_actual / actual_lines_total

    # Final weighted score
    reward = 0.35 * file_recall + 0.45 * line_recall + 0.20 * line_precision

    return {
        "file_recall": round(file_recall, 4),
        "line_recall": round(line_recall, 4),
        "line_precision": round(line_precision, 4),
        "reward": round(reward, 4),
        "expected_files": sorted(expected_files),
        "actual_files": sorted(actual_files),
        "expected_lines_total": expected_lines_total,
        "actual_lines_total": actual_lines_total,
    }


def get_agent_diff(pre_fix_rev: str, workspace: str = "/workspace") -> str:
    """Run git diff against pre_fix_rev in the workspace."""
    try:
        result = subprocess.run(
            ["git", "diff", pre_fix_rev],
            capture_output=True,
            text=True,
            cwd=workspace,
            timeout=60,
        )
        return result.stdout
    except Exception as e:
        print(f"Error running git diff: {e}", file=sys.stderr)
        return ""


def main():
    parser = argparse.ArgumentParser(description="Diff-based verifier for PyTorch tasks")
    parser.add_argument("--expected", required=True, help="Path to expected.diff file")
    parser.add_argument("--pre-fix-rev", required=True, help="Git commit hash of pre-fix revision")
    parser.add_argument("--output", required=True, help="Path to output reward.json")
    parser.add_argument("--workspace", default="/workspace", help="Workspace directory")
    args = parser.parse_args()

    # Read expected diff
    if not os.path.isfile(args.expected):
        print(f"ERROR: Expected diff not found: {args.expected}")
        result = {"reward": 0.0, "error": "expected.diff not found"}
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        return

    with open(args.expected) as f:
        expected_text = f.read()

    expected = parse_unified_diff(expected_text)
    print(f"Expected diff: {len(expected)} files, "
          f"{sum(len(v['added']) + len(v['removed']) for v in expected.values())} lines")

    # Get agent's diff
    agent_text = get_agent_diff(args.pre_fix_rev, args.workspace)

    # No-op gate
    if not agent_text.strip():
        print("GATE: No changes detected vs pre_fix_rev. Reward = 0.0")
        result = {"reward": 0.0, "gate": "no_changes"}
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        return

    actual = parse_unified_diff(agent_text)
    print(f"Agent diff: {len(actual)} files, "
          f"{sum(len(v['added']) + len(v['removed']) for v in actual.values())} lines")

    # Compute scores
    scores = compute_scores(expected, actual)
    print(f"Scores: file_recall={scores['file_recall']}, "
          f"line_recall={scores['line_recall']}, "
          f"line_precision={scores['line_precision']}")
    print(f"Final reward: {scores['reward']}")

    # Write output
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(scores, f, indent=2)


if __name__ == "__main__":
    main()
