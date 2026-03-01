#!/usr/bin/env bash

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh
# Artifact mode: parse answer.json, extract analysis text
if [ -f /tmp/.artifact_only_mode ] && [ -f /tests/answer_json_verifier_lib.sh ]; then
    source /tests/answer_json_verifier_lib.sh
fi

set -euo pipefail

# Migration guide verifier using weighted checklist scoring
# Validates documentation.md against ground_truth.json

GROUND_TRUTH_FILE="/tests/ground_truth.json"
DOCUMENTATION_FILE="/workspace/documentation.md"
# In artifact mode, populate expected output from answer.json analysis
if [ "${ARTIFACT_ONLY:-false}" = "true" ] && [ -f "${ANALYSIS_TEXT_FILE:-}" ]; then
    cp "$ANALYSIS_TEXT_FILE" "/workspace/documentation.md"
    echo "[answer_json] Copied analysis text to /workspace/documentation.md"
fi
REWARD_FILE="/logs/verifier/reward.txt"

mkdir -p /logs/verifier

if [[ ! -f "$DOCUMENTATION_FILE" ]]; then
    echo "FAIL: documentation.md not found at /workspace/documentation.md"
    echo "0.0" > "$REWARD_FILE"
    exit 0
fi

if [[ ! -f "$GROUND_TRUTH_FILE" ]]; then
    echo "FAIL: ground_truth.json not found"
    echo "0.0" > "$REWARD_FILE"
    exit 0
fi

REWARD_FILE="$REWARD_FILE" python3 - <<'PYTHON_SCRIPT'
import json
import os
import re
import sys

REWARD_PATH = os.environ["REWARD_FILE"]

def write_reward(score):
    with open(REWARD_PATH, "w") as f:
        f.write(f"{score:.2f}\n")
    print(f"\nTests completed - Score: {score:.2f}")

def load_json(path):
    with open(path, 'r') as f:
        return json.load(f)

def load_documentation(path):
    with open(path, 'r') as f:
        return f.read()

def check_patterns(text, patterns, check_all=False):
    """
    Check if patterns match in text.
    check_all=True: all patterns must match (AND)
    check_all=False: any pattern must match (OR)
    """
    matches = [bool(re.search(pattern, text, re.DOTALL | re.MULTILINE)) for pattern in patterns]

    if check_all:
        return all(matches)
    else:
        return any(matches)

def score_category(text, category_data):
    """Score a category by checking each item's patterns."""
    total_score = 0.0
    max_score = 0.0

    for item in category_data['items']:
        patterns = item['patterns']
        weight = item['weight']
        max_score += weight

        # For migration guides, use OR logic (any pattern matches)
        if check_patterns(text, patterns, check_all=False):
            total_score += weight

    return total_score, max_score

def main():
    try:
        ground_truth = load_json('/tests/ground_truth.json')
        documentation = load_documentation('/workspace/documentation.md')
    except Exception as e:
        print(f"Error loading files: {e}")
        write_reward(0.0)
        return

    categories = ground_truth['scoring_categories']

    overall_score = 0.0

    print("=" * 60)
    print("Migration Guide Scoring Report")
    print("=" * 60)

    for category_name, category_data in categories.items():
        category_weight = category_data['weight']
        score, max_score = score_category(documentation, category_data)

        if max_score > 0:
            normalized_score = score / max_score
        else:
            normalized_score = 0.0

        weighted_score = normalized_score * category_weight
        overall_score += weighted_score

        print(f"\n{category_name}:")
        print(f"  Raw: {score:.2f}/{max_score:.2f}")
        print(f"  Normalized: {normalized_score:.3f}")
        print(f"  Weighted (x{category_weight}): {weighted_score:.3f}")

    print("\n" + "=" * 60)
    print(f"Overall Score: {overall_score:.3f}")
    print("=" * 60)

    write_reward(overall_score)

if __name__ == '__main__':
    main()
PYTHON_SCRIPT
