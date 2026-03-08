#!/usr/bin/env python3
"""Suite-aware verifier for promoted Org→SDLC tasks.

Wraps oracle_checks.py with suite-specific composite weights and detailed
validation output. Designed to be deployed alongside oracle_checks.py in
each promoted task's tests/ directory.

Stdlib only — no external dependencies.

Usage:
    python3 promoted_verifier.py \
        --answer /workspace/answer.json \
        --spec /tests/task_spec.json \
        --suite csb_sdlc_understand \
        --output /logs/verifier/validation_result.json

Exit codes:
    0 — composite score > 0
    1 — composite score == 0
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

# Import oracle_checks from the same directory
sys.path.insert(0, str(Path(__file__).parent))
from oracle_checks import (
    check_dependency_chain,
    check_file_set_match,
    check_keyword_presence,
    check_provenance,
    check_symbol_resolution,
    run_all_checks,
)

# ---------------------------------------------------------------------------
# Suite-specific composite weights
# ---------------------------------------------------------------------------
# Each suite emphasizes different oracle dimensions. Weights must sum to 1.0.
# Checks not present in a task's spec get their weight redistributed to the
# remaining checks proportionally.

SUITE_WEIGHTS: Dict[str, Dict[str, float]] = {
    "csb_sdlc_understand": {
        "file_set_match": 0.40,
        "symbol_resolution": 0.25,
        "dependency_chain": 0.20,
        "keyword_presence": 0.15,
    },
    "csb_sdlc_design": {
        "file_set_match": 0.25,
        "symbol_resolution": 0.15,
        "dependency_chain": 0.40,
        "keyword_presence": 0.20,
    },
    "csb_sdlc_debug": {
        "file_set_match": 0.50,
        "symbol_resolution": 0.20,
        "keyword_presence": 0.30,
    },
    "csb_sdlc_secure": {
        "file_set_match": 0.40,
        "keyword_presence": 0.30,
        "symbol_resolution": 0.20,
        "provenance": 0.10,
    },
    "csb_sdlc_refactor": {
        "file_set_match": 0.40,
        "symbol_resolution": 0.25,
        "dependency_chain": 0.20,
        "keyword_presence": 0.15,
    },
    "csb_sdlc_test": {
        "file_set_match": 0.50,
        "keyword_presence": 0.30,
        "symbol_resolution": 0.20,
    },
}

# Score extraction keys per check type (must match oracle_checks.py)
SCORE_KEYS: Dict[str, str] = {
    "file_set_match": "f1",  # will prefer weighted_f1 if available
    "symbol_resolution": "recall",
    "dependency_chain": "chain_recall",
    "keyword_presence": "keyword_recall",
    "provenance": "provenance_score",
}


def _extract_score(check_result: Dict[str, Any], check_type: str) -> float:
    """Extract the primary score from a check result."""
    if check_type == "file_set_match":
        return float(check_result.get("weighted_f1", check_result.get("f1", 0)))
    key = SCORE_KEYS.get(check_type, "")
    val = check_result.get(key, 0)
    return float(val) if not isinstance(val, bool) else (1.0 if val else 0.0)


def compute_weighted_composite(
    check_results: Dict[str, Dict[str, Any]],
    target_suite: str,
) -> Dict[str, Any]:
    """Compute suite-weighted composite from per-check results.

    Returns a dict with composite_score, per-check scores, and weight info.
    """
    weights = SUITE_WEIGHTS.get(target_suite, SUITE_WEIGHTS["csb_sdlc_understand"])

    # Filter to checks that are actually present in results
    active_weights = {k: v for k, v in weights.items() if k in check_results}

    # Redistribute weights of missing checks proportionally
    if active_weights:
        total_active = sum(active_weights.values())
        normalized = {k: v / total_active for k, v in active_weights.items()}
    else:
        normalized = {}

    per_check = {}
    weighted_sum = 0.0
    for check_type, weight in normalized.items():
        score = _extract_score(check_results[check_type], check_type)
        per_check[check_type] = {
            "score": round(score, 4),
            "weight": round(weight, 4),
            "weighted_contribution": round(score * weight, 4),
        }
        weighted_sum += score * weight

    # Also include any checks not in the weight table (e.g., provenance for non-secure tasks)
    for check_type, result in check_results.items():
        if check_type not in per_check:
            score = _extract_score(result, check_type)
            per_check[check_type] = {
                "score": round(score, 4),
                "weight": 0.0,
                "weighted_contribution": 0.0,
                "note": "not in suite weight table",
            }

    return {
        "composite_score": round(weighted_sum, 4),
        "target_suite": target_suite,
        "weights_used": {k: round(v, 4) for k, v in normalized.items()},
        "per_check": per_check,
    }


def run_promoted_verifier(
    answer_path: str,
    task_spec_path: str,
    target_suite: str,
    output_path: str | None = None,
) -> Dict[str, Any]:
    """Run oracle checks with suite-specific weighting.

    Returns full result dict. Optionally writes to output_path.
    """
    # Run base oracle checks
    base_result = run_all_checks(answer_path, task_spec_path)

    if "error" in base_result:
        result = {
            "composite_score": 0.0,
            "error": base_result["error"],
            "target_suite": target_suite,
            "oracle_checks": base_result,
        }
    else:
        # Compute suite-weighted composite
        weighted = compute_weighted_composite(
            base_result.get("checks", {}), target_suite
        )
        result = {
            "composite_score": weighted["composite_score"],
            "target_suite": target_suite,
            "weights_used": weighted["weights_used"],
            "per_check": weighted["per_check"],
            "oracle_checks": base_result,
        }

    # Write output file
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w") as f:
            json.dump(result, f, indent=2)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Suite-aware verifier for promoted Org→SDLC tasks."
    )
    parser.add_argument("--answer", required=True, help="Path to answer.json")
    parser.add_argument("--spec", required=True, help="Path to task_spec.json")
    parser.add_argument(
        "--suite", required=True, help="Target SDLC suite (e.g., csb_sdlc_understand)"
    )
    parser.add_argument(
        "--output", default=None, help="Path to write validation_result.json"
    )
    parser.add_argument("--verbose", action="store_true", help="Print detailed results")
    args = parser.parse_args()

    result = run_promoted_verifier(args.answer, args.spec, args.suite, args.output)

    if args.verbose:
        print(json.dumps(result, indent=2), file=sys.stderr)

    # Print composite score to stdout (matches oracle_checks.py convention)
    print(f"{result['composite_score']:.4f}")

    sys.exit(0 if result["composite_score"] > 0 else 1)


if __name__ == "__main__":
    main()
