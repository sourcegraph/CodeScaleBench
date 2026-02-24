#!/usr/bin/env python3
"""Deterministic oracle check library for MCP-unique benchmark evaluation.

Provides reusable check functions that eval.sh scripts invoke to score agent
answers against closed-world oracle definitions. Returns raw scores (no
pass/fail thresholds) to enable calibration.

Stdlib only — no external dependencies.

Usage (CLI):
    python3 oracle_checks.py --answer answer.json --spec task_spec.json

Usage (library):
    from ccb_metrics.oracle_checks import check_file_set_match, run_all_checks

Exit codes:
    0 — composite score > 0 (agent produced useful output)
    1 — composite score == 0 (total failure)
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def check_file_set_match(
    answer_files: List[Dict[str, str]],
    oracle_files: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Check overlap between agent-reported files and oracle files.

    Each file item is a dict with at least {"repo", "path"}.
    Matching is by (repo, path) tuple — both must match.

    Returns raw scores without thresholds.

    >>> result = check_file_set_match(
    ...     [{"repo": "a/b", "path": "x.go"}],
    ...     [{"repo": "a/b", "path": "x.go"}, {"repo": "a/b", "path": "y.go"}],
    ... )
    >>> result["recall"]
    0.5
    >>> result["precision"]
    1.0
    >>> result["matched"]
    [{'repo': 'a/b', 'path': 'x.go'}]
    """
    def _key(item: Dict[str, str]) -> tuple:
        return (item.get("repo", ""), item.get("path", ""))

    oracle_set = {_key(f) for f in oracle_files}
    answer_set = {_key(f) for f in answer_files}

    matched = oracle_set & answer_set
    missing = oracle_set - answer_set
    extra = answer_set - oracle_set

    recall = len(matched) / len(oracle_set) if oracle_set else 1.0
    precision = len(matched) / len(answer_set) if answer_set else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    return {
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "f1": round(f1, 4),
        "matched": [{"repo": r, "path": p} for r, p in sorted(matched)],
        "missing": [{"repo": r, "path": p} for r, p in sorted(missing)],
        "extra": [{"repo": r, "path": p} for r, p in sorted(extra)],
    }


def check_symbol_resolution(
    answer_symbols: List[Dict[str, str]],
    oracle_symbols: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Check overlap between agent-identified symbols and oracle symbols.

    Each symbol item has at least {"repo", "path", "symbol"}.
    Matching is by (repo, path, symbol) tuple.

    >>> result = check_symbol_resolution(
    ...     [{"repo": "a/b", "path": "x.go", "symbol": "Foo"}],
    ...     [{"repo": "a/b", "path": "x.go", "symbol": "Foo"}],
    ... )
    >>> result["recall"]
    1.0
    """
    def _key(item: Dict[str, str]) -> tuple:
        return (item.get("repo", ""), item.get("path", ""), item.get("symbol", ""))

    oracle_set = {_key(s) for s in oracle_symbols}
    answer_set = {_key(s) for s in answer_symbols}

    matched = oracle_set & answer_set
    missing = oracle_set - answer_set
    extra = answer_set - oracle_set

    recall = len(matched) / len(oracle_set) if oracle_set else 1.0
    precision = len(matched) / len(answer_set) if answer_set else 0.0

    return {
        "matched": [{"repo": r, "path": p, "symbol": s} for r, p, s in sorted(matched)],
        "missing": [{"repo": r, "path": p, "symbol": s} for r, p, s in sorted(missing)],
        "extra": [{"repo": r, "path": p, "symbol": s} for r, p, s in sorted(extra)],
        "recall": round(recall, 4),
        "precision": round(precision, 4),
    }


def check_dependency_chain(
    answer_chain: List[Dict[str, str]],
    oracle_chain: List[Dict[str, str]],
) -> Dict[str, Any]:
    """Check if agent traced the correct dependency chain.

    Each step is {"repo", "path", "symbol"}. Order matters — we check both
    set membership (did agent find the step?) and order (is the sequence
    correct?).

    >>> result = check_dependency_chain(
    ...     [{"repo": "a", "path": "x", "symbol": "f1"},
    ...      {"repo": "b", "path": "y", "symbol": "f2"}],
    ...     [{"repo": "a", "path": "x", "symbol": "f1"},
    ...      {"repo": "b", "path": "y", "symbol": "f2"}],
    ... )
    >>> result["order_correct"]
    True
    >>> result["chain_recall"]
    1.0
    """
    def _key(item: Dict[str, str]) -> tuple:
        return (item.get("repo", ""), item.get("path", ""), item.get("symbol", ""))

    oracle_keys = [_key(s) for s in oracle_chain]
    answer_keys = [_key(s) for s in answer_chain]

    oracle_set = set(oracle_keys)
    answer_set = set(answer_keys)

    matched = oracle_set & answer_set
    missing = oracle_set - answer_set

    # Check order: extract the subsequence of answer that matches oracle steps
    # and verify it preserves the oracle ordering.
    oracle_positions = {k: i for i, k in enumerate(oracle_keys)}
    matched_in_order = [k for k in answer_keys if k in oracle_set]
    positions = [oracle_positions[k] for k in matched_in_order if k in oracle_positions]
    order_correct = positions == sorted(positions) and len(matched) == len(oracle_set)

    chain_recall = len(matched) / len(oracle_set) if oracle_set else 1.0

    return {
        "matched_steps": len(matched),
        "missing_steps": [{"repo": r, "path": p, "symbol": s} for r, p, s in sorted(missing)],
        "order_correct": order_correct,
        "chain_recall": round(chain_recall, 4),
    }


def check_provenance(
    answer: str,
    must_cite_paths: Optional[List[str]] = None,
    must_cite_repos: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Check that the agent's answer cites required paths and repos.

    Simple substring matching — if "kubernetes/kubernetes" appears anywhere
    in the answer text, it counts as cited.

    >>> result = check_provenance(
    ...     "Found in kubernetes/kubernetes at pkg/api/types.go",
    ...     must_cite_paths=["pkg/api/types.go", "cmd/main.go"],
    ...     must_cite_repos=["kubernetes/kubernetes"],
    ... )
    >>> result["provenance_score"]
    0.6667
    """
    must_cite_paths = must_cite_paths or []
    must_cite_repos = must_cite_repos or []

    all_citations = must_cite_paths + must_cite_repos
    found = [c for c in all_citations if c in answer]
    missing = [c for c in all_citations if c not in answer]

    total = len(all_citations)
    score = len(found) / total if total > 0 else 1.0

    return {
        "citations_found": found,
        "citations_missing": missing,
        "citations_valid": len(found),
        "provenance_score": round(score, 4),
    }


def check_keyword_presence(
    answer_text: str,
    required_keywords: List[str],
) -> Dict[str, Any]:
    """Check that required keywords appear in the answer.

    Case-insensitive substring matching.

    >>> result = check_keyword_presence("The Foo function calls Bar", ["foo", "bar", "baz"])
    >>> result["keyword_recall"]
    0.6667
    >>> sorted(result["found"])
    ['bar', 'foo']
    """
    answer_lower = answer_text.lower()
    found = [kw for kw in required_keywords if kw.lower() in answer_lower]
    missing = [kw for kw in required_keywords if kw.lower() not in answer_lower]

    total = len(required_keywords)
    recall = len(found) / total if total > 0 else 1.0

    return {
        "found": found,
        "missing": missing,
        "total": total,
        "keyword_recall": round(recall, 4),
    }


def check_json_schema(
    answer_json: Any,
    schema_path: str,
) -> Dict[str, Any]:
    """Validate answer JSON against a JSON Schema file.

    Uses stdlib json only. Performs basic structural checks without
    a full JSON Schema validator (to stay stdlib-only). Checks:
    - answer_json is valid JSON (dict or list)
    - schema file exists and is valid JSON

    >>> result = check_json_schema({"key": "value"}, "/nonexistent.json")
    >>> result["valid"]
    False
    """
    errors = []

    if not isinstance(answer_json, (dict, list)):
        errors.append("Answer is not a JSON object or array")

    schema_file = Path(schema_path)
    if not schema_file.exists():
        errors.append(f"Schema file not found: {schema_path}")
    else:
        try:
            with open(schema_file) as f:
                schema = json.load(f)
            # Basic type check
            if "type" in schema:
                expected = schema["type"]
                actual = "object" if isinstance(answer_json, dict) else "array" if isinstance(answer_json, list) else type(answer_json).__name__
                if expected != actual:
                    errors.append(f"Type mismatch: expected {expected}, got {actual}")
            # Check required fields
            if "required" in schema and isinstance(answer_json, dict):
                for field in schema["required"]:
                    if field not in answer_json:
                        errors.append(f"Missing required field: {field}")
        except (json.JSONDecodeError, OSError) as e:
            errors.append(f"Schema parse error: {e}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
    }


def check_test_ratio(
    test_command: str,
    workspace_dir: str,
) -> Dict[str, Any]:
    """Run tests and compute pass/fail ratio for Category I code-gen tasks.

    Executes the test command in the workspace directory. Parses exit code
    and any structured output to determine pass/fail counts.

    >>> # Cannot run actual tests in doctest
    """
    result = {"passed": 0, "failed": 0, "total": 0, "ratio": 0.0}

    if not os.path.isdir(workspace_dir):
        result["error"] = f"Workspace not found: {workspace_dir}"
        return result

    try:
        proc = subprocess.run(
            test_command,
            shell=True,
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )

        # Try to parse structured test output (pytest-style, go test, etc.)
        output = proc.stdout + proc.stderr

        # Count lines with PASS/FAIL/ok/FAIL patterns
        passed = 0
        failed = 0
        for line in output.splitlines():
            line_stripped = line.strip()
            if line_stripped.startswith("ok ") or "PASS" in line_stripped:
                passed += 1
            elif line_stripped.startswith("FAIL") or line_stripped.startswith("--- FAIL"):
                failed += 1

        # Fallback: if no structured output, use exit code
        if passed == 0 and failed == 0:
            if proc.returncode == 0:
                passed = 1
            else:
                failed = 1

        total = passed + failed
        ratio = passed / total if total > 0 else 0.0

        result = {
            "passed": passed,
            "failed": failed,
            "total": total,
            "ratio": round(ratio, 4),
        }

    except subprocess.TimeoutExpired:
        result["error"] = "Test command timed out after 300s"
    except OSError as e:
        result["error"] = f"Test execution error: {e}"

    return result


def _get_primary_score(check_result: Dict[str, Any], check_type: str) -> float:
    """Extract the primary score from a check result for composite scoring."""
    score_keys = {
        "file_set_match": "f1",
        "symbol_resolution": "recall",
        "dependency_chain": "chain_recall",
        "provenance": "provenance_score",
        "keyword_presence": "keyword_recall",
        "json_schema_match": "valid",
        "test_ratio": "ratio",
    }
    key = score_keys.get(check_type, "")
    value = check_result.get(key, 0)
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    return float(value)


def run_all_checks(
    answer_path: str,
    task_spec_path: str,
) -> Dict[str, Any]:
    """Run all checks defined in the task spec against the answer.

    Reads the task_spec.json for oracle definitions and evaluation checks,
    loads the answer file, and runs each configured check. Computes a
    composite score as the mean of individual check scores.

    Returns aggregate results dict with per-check details and composite_score.
    """
    # Load files
    try:
        with open(answer_path) as f:
            answer_data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {"error": f"Cannot load answer: {e}", "composite_score": 0.0, "checks": {}}

    try:
        with open(task_spec_path) as f:
            spec = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {"error": f"Cannot load task spec: {e}", "composite_score": 0.0, "checks": {}}

    oracle = spec.get("artifacts", {}).get("oracle", {})
    eval_checks = spec.get("evaluation", {}).get("checks", [])

    # If answer is a dict with "text" key, extract the text for text-based checks
    answer_text = ""
    if isinstance(answer_data, dict):
        answer_text = answer_data.get("text", answer_data.get("answer", json.dumps(answer_data)))
    elif isinstance(answer_data, str):
        answer_text = answer_data

    # Extract structured lists from answer
    answer_files = answer_data.get("files", []) if isinstance(answer_data, dict) else []
    answer_symbols = answer_data.get("symbols", []) if isinstance(answer_data, dict) else []
    answer_chain = answer_data.get("chain", answer_data.get("dependency_chain", [])) if isinstance(answer_data, dict) else []

    results = {}
    scores = []

    for check in eval_checks:
        check_type = check.get("type", "")
        params = check.get("params", {})

        if check_type == "file_set_match":
            oracle_files = oracle.get("required_files", [])
            result = check_file_set_match(answer_files, oracle_files)

        elif check_type == "symbol_resolution":
            oracle_symbols = oracle.get("required_symbols", [])
            result = check_symbol_resolution(answer_symbols, oracle_symbols)

        elif check_type == "dependency_chain":
            oracle_chains = oracle.get("dependency_chains", [])
            # Aggregate across all chains
            if oracle_chains:
                chain_results = []
                for oc in oracle_chains:
                    steps = oc.get("steps", [])
                    cr = check_dependency_chain(answer_chain, steps)
                    chain_results.append(cr)
                # Average chain_recall across all chains
                avg_recall = sum(cr["chain_recall"] for cr in chain_results) / len(chain_results)
                result = {
                    "chains": chain_results,
                    "chain_recall": round(avg_recall, 4),
                    "order_correct": all(cr["order_correct"] for cr in chain_results),
                    "matched_steps": sum(cr["matched_steps"] for cr in chain_results),
                    "missing_steps": [s for cr in chain_results for s in cr["missing_steps"]],
                }
            else:
                result = {"chain_recall": 1.0, "chains": [], "order_correct": True, "matched_steps": 0, "missing_steps": []}

        elif check_type == "provenance":
            result = check_provenance(
                answer_text,
                must_cite_paths=params.get("must_cite_paths", []),
                must_cite_repos=params.get("must_cite_repos", []),
            )

        elif check_type == "keyword_presence":
            result = check_keyword_presence(
                answer_text,
                required_keywords=params.get("required_keywords", []),
            )

        elif check_type == "json_schema_match":
            result = check_json_schema(
                answer_data,
                schema_path=params.get("schema_path", ""),
            )

        elif check_type == "test_ratio":
            result = check_test_ratio(
                test_command=params.get("test_command", "echo no-test"),
                workspace_dir=params.get("workspace_dir", "/workspace"),
            )

        else:
            result = {"error": f"Unknown check type: {check_type}"}

        results[check_type] = result
        scores.append(_get_primary_score(result, check_type))

    composite = sum(scores) / len(scores) if scores else 0.0

    return {
        "checks": results,
        "composite_score": round(composite, 4),
        "num_checks": len(scores),
        "individual_scores": [round(s, 4) for s in scores],
    }


def main() -> None:
    """CLI entrypoint for oracle checks."""
    parser = argparse.ArgumentParser(
        description="Run oracle checks against an agent answer."
    )
    parser.add_argument(
        "--answer", required=True,
        help="Path to the agent's answer JSON file."
    )
    parser.add_argument(
        "--spec", required=True,
        help="Path to the task_spec.json file."
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print detailed check results."
    )
    args = parser.parse_args()

    result = run_all_checks(args.answer, args.spec)

    if args.verbose:
        print(json.dumps(result, indent=2), file=sys.stderr)

    # Write composite score to stdout
    print(f"{result['composite_score']:.4f}")

    # Exit 0 if composite > 0, exit 1 if composite == 0
    sys.exit(0 if result["composite_score"] > 0 else 1)


if __name__ == "__main__":
    main()
