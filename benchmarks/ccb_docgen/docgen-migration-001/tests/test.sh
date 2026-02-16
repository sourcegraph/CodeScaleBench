#!/usr/bin/env bash
set -euo pipefail

# Migration guide verifier using weighted checklist scoring
# Validates documentation.md against ground_truth.json

GROUND_TRUTH_FILE="$(dirname "$0")/ground_truth.json"
DOCUMENTATION_FILE="/workspace/documentation.md"

if [[ ! -f "$DOCUMENTATION_FILE" ]]; then
    echo "FAIL: documentation.md not found at /workspace/documentation.md"
    exit 1
fi

if [[ ! -f "$GROUND_TRUTH_FILE" ]]; then
    echo "FAIL: ground_truth.json not found"
    exit 1
fi

python3 - <<'PYTHON_SCRIPT'
import json
import re
import sys
from pathlib import Path

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
        # This is more forgiving than architecture docs
        if check_patterns(text, patterns, check_all=False):
            total_score += weight

    return total_score, max_score

def main():
    ground_truth = load_json('benchmarks/ccb_docgen/docgen-migration-001/tests/ground_truth.json')
    documentation = load_documentation('/workspace/documentation.md')

    categories = ground_truth['scoring_categories']

    overall_score = 0.0
    category_scores = {}

    print("=" * 60)
    print("Migration Guide Scoring Report")
    print("=" * 60)

    for category_name, category_data in categories.items():
        category_weight = category_data['weight']
        score, max_score = score_category(documentation, category_data)

        # Normalize to 0-1 range for this category
        if max_score > 0:
            normalized_score = score / max_score
        else:
            normalized_score = 0.0

        # Weight by category importance
        weighted_score = normalized_score * category_weight
        overall_score += weighted_score

        category_scores[category_name] = {
            'raw_score': score,
            'max_score': max_score,
            'normalized': normalized_score,
            'weighted': weighted_score
        }

        print(f"\n{category_name}:")
        print(f"  Raw: {score:.2f}/{max_score:.2f}")
        print(f"  Normalized: {normalized_score:.3f}")
        print(f"  Weighted (x{category_weight}): {weighted_score:.3f}")

    print("\n" + "=" * 60)
    print(f"Overall Score: {overall_score:.3f}")
    print("=" * 60)

    # Pass threshold: 0.7
    if overall_score >= 0.7:
        print("\nRESULT: PASS")
        sys.exit(0)
    else:
        print(f"\nRESULT: FAIL (score {overall_score:.3f} < 0.7 threshold)")
        sys.exit(1)

if __name__ == '__main__':
    main()
PYTHON_SCRIPT
