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
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict

SCRIPT_DIR = Path(__file__).parent


def _load_run_all_checks():
    """Load oracle_checks.py from the copied task dir or the repo copy."""
    candidates = (
        SCRIPT_DIR / "oracle_checks.py",
        SCRIPT_DIR / "csb_metrics" / "oracle_checks.py",
    )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        spec = importlib.util.spec_from_file_location("oracle_checks", candidate)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.run_all_checks
    raise ModuleNotFoundError("oracle_checks.py not found next to promoted_verifier.py")


run_all_checks = _load_run_all_checks()

# ---------------------------------------------------------------------------
# Suite-specific composite weights
# ---------------------------------------------------------------------------
# Each suite emphasizes different oracle dimensions. Weights must sum to 1.0.
# Checks not present in a task's spec get their weight redistributed to the
# remaining checks proportionally.

SUITE_WEIGHTS: Dict[str, Dict[str, float]] = {
    # --- Unified csb/ suites (merged) ---
    "csb_understand": {  # sdlc_understand + sdlc_design + org_domain + org_onboarding
        "file_set_match": 0.35,
        "symbol_resolution": 0.20,
        "dependency_chain": 0.25,
        "keyword_presence": 0.20,
    },
    "csb_debug": {  # sdlc_debug + org_incident
        "file_set_match": 0.50,
        "symbol_resolution": 0.20,
        "keyword_presence": 0.30,
    },
    "csb_security": {  # sdlc_secure + org_security + org_compliance
        "file_set_match": 0.40,
        "keyword_presence": 0.30,
        "symbol_resolution": 0.20,
        "provenance": 0.10,
    },
    "csb_refactor": {  # sdlc_refactor + org_migration
        "file_set_match": 0.40,
        "symbol_resolution": 0.25,
        "dependency_chain": 0.20,
        "keyword_presence": 0.15,
    },
    "csb_feature": {  # sdlc_feature + org_org
        "file_set_match": 0.40,
        "symbol_resolution": 0.25,
        "dependency_chain": 0.20,
        "keyword_presence": 0.15,
    },
    "csb_fix": {  # sdlc_fix
        "file_set_match": 0.50,
        "symbol_resolution": 0.20,
        "keyword_presence": 0.30,
    },
    "csb_test": {  # sdlc_test
        "file_set_match": 0.50,
        "keyword_presence": 0.30,
        "symbol_resolution": 0.20,
    },
    "csb_document": {  # sdlc_document
        "file_set_match": 0.35,
        "keyword_presence": 0.40,
        "symbol_resolution": 0.15,
        "provenance": 0.10,
    },
    "csb_crossrepo": {  # org_crossrepo + org_crossrepo_tracing + org_crossorg + org_platform
        "file_set_match": 0.30,
        "symbol_resolution": 0.20,
        "dependency_chain": 0.35,
        "keyword_presence": 0.15,
    },
    # --- Legacy suite keys (backward compat for existing runs) ---
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

VALIDATION_RESULT_SCHEMA_VERSION = "validation_result.v1alpha1"
DEFAULT_PASS_THRESHOLD = 0.0
DEFAULT_OUTPUT_CONTRACT: Dict[str, Any] = {
    "mode": "answer_json_native",
    "primary_path": "/workspace/answer.json",
    "required_artifact": True,
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
    weights = SUITE_WEIGHTS.get(target_suite, SUITE_WEIGHTS["csb_understand"])

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


def _canonicalize_sub_scores(per_check: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Normalize suite-weighted check data into the shared sub_scores shape."""
    sub_scores: Dict[str, Dict[str, Any]] = {}
    for check_type, info in per_check.items():
        score = float(info.get("score", 0.0))
        entry: Dict[str, Any] = {
            "score": round(score, 4),
            "passed": score > 0.0,
        }
        for key in ("weight", "weighted_contribution", "note"):
            if key in info:
                entry[key] = info[key]
        sub_scores[check_type] = entry
    return sub_scores


def _build_validation_result(
    reward: float,
    target_suite: str,
    sub_scores: Dict[str, Dict[str, Any]],
    failure: Dict[str, str] | None,
    legacy_fields: Dict[str, Any],
    details: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the canonical validation_result payload while preserving legacy keys."""
    reward = round(float(reward), 4)
    result: Dict[str, Any] = {
        "schema_version": VALIDATION_RESULT_SCHEMA_VERSION,
        "status": "scored" if failure is None else (
            "invalid_output" if failure.get("stage") == "output_validation" else "verifier_error"
        ),
        "scorable": failure is None,
        "scorer_family": "oracle_checks",
        "reward": reward,
        "pass_threshold": DEFAULT_PASS_THRESHOLD,
        "passed": failure is None and reward > DEFAULT_PASS_THRESHOLD,
        "output_contract": dict(DEFAULT_OUTPUT_CONTRACT),
        "sub_scores": sub_scores,
        "failure": failure,
        "details": {
            "reward_type": "score",
            "target_suite": target_suite,
            **details,
        },
    }
    result.update(legacy_fields)
    return result


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
        result = _build_validation_result(
            reward=0.0,
            target_suite=target_suite,
            sub_scores={},
            failure={
                "code": "oracle_checks_error",
                "message": str(base_result["error"]),
                "stage": "scoring",
            },
            legacy_fields={
                "composite_score": 0.0,
                "error": base_result["error"],
                "target_suite": target_suite,
                "oracle_checks": base_result,
                "per_check": {},
                "weights_used": {},
            },
            details={
                "oracle_checks": base_result,
                "weights_used": {},
            },
        )
    else:
        # Compute suite-weighted composite
        weighted = compute_weighted_composite(
            base_result.get("checks", {}), target_suite
        )
        result = _build_validation_result(
            reward=weighted["composite_score"],
            target_suite=target_suite,
            sub_scores=_canonicalize_sub_scores(weighted["per_check"]),
            failure=None,
            legacy_fields={
                "composite_score": weighted["composite_score"],
                "target_suite": target_suite,
                "weights_used": weighted["weights_used"],
                "per_check": weighted["per_check"],
                "oracle_checks": base_result,
            },
            details={
                "weights_used": weighted["weights_used"],
                "oracle_checks": base_result,
            },
        )

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
