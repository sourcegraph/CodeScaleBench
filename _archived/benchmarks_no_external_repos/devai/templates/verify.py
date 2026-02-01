#!/usr/bin/env python3
"""
DevAI Verifier

Validates agent trajectories against trajectory-schema.json and computes
scores based on requirement satisfaction.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def validate_trajectory_schema(
    trajectory: dict[str, Any],
    schema: dict[str, Any],
) -> tuple[bool, list[str]]:
    """
    Validate trajectory against JSON schema.

    Simple validation without external dependencies.

    Args:
        trajectory: Trajectory data to validate.
        schema: JSON schema to validate against.

    Returns:
        Tuple of (is_valid, list of error messages).
    """
    errors: list[str] = []

    # Check required fields
    required = schema.get("properties", {}).keys()
    for field in schema.get("required", []):
        if field not in trajectory:
            errors.append(f"Missing required field: {field}")

    # Check task_id
    if "task_id" in trajectory:
        if not isinstance(trajectory["task_id"], str):
            errors.append("task_id must be a string")

    # Check steps
    if "steps" in trajectory:
        if not isinstance(trajectory["steps"], list):
            errors.append("steps must be an array")
        else:
            for i, step in enumerate(trajectory["steps"]):
                if not isinstance(step, dict):
                    errors.append(f"Step {i} must be an object")
                elif "step_number" not in step:
                    errors.append(f"Step {i} missing step_number")
                elif "action" not in step:
                    errors.append(f"Step {i} missing action")
                elif "observation" not in step:
                    errors.append(f"Step {i} missing observation")

    # Check final_state
    if "final_state" in trajectory:
        if not isinstance(trajectory["final_state"], dict):
            errors.append("final_state must be an object")

    return len(errors) == 0, errors


def compute_requirement_score(
    trajectory: dict[str, Any],
    ground_truth: dict[str, Any],
) -> dict[str, Any]:
    """
    Compute score based on requirement satisfaction.

    Args:
        trajectory: Agent trajectory data.
        ground_truth: Ground truth with requirements.

    Returns:
        Score details dictionary.
    """
    requirements = ground_truth.get("requirements", [])
    total_requirements = len(requirements)

    if total_requirements == 0:
        return {
            "score": 1.0 if trajectory.get("final_state", {}).get("completed", False) else 0.0,
            "requirement_scores": {},
            "total_requirements": 0,
            "met_requirements": 0,
        }

    # Get requirements met from trajectory final_state
    final_state = trajectory.get("final_state", {})
    requirements_met = final_state.get("requirements_met", {})

    # Count met requirements
    met_count = 0
    requirement_scores: dict[str, float] = {}

    for req in requirements:
        req_id = req.get("id", "")
        if req_id in requirements_met:
            is_met = requirements_met[req_id]
            requirement_scores[req_id] = 1.0 if is_met else 0.0
            if is_met:
                met_count += 1
        else:
            # If not explicitly listed, assume not met
            requirement_scores[req_id] = 0.0

    # Compute overall score as fraction of requirements met
    score = met_count / total_requirements if total_requirements > 0 else 0.0

    return {
        "score": round(score, 4),
        "requirement_scores": requirement_scores,
        "total_requirements": total_requirements,
        "met_requirements": met_count,
    }


def compute_score(
    trajectory: dict[str, Any],
    ground_truth: dict[str, Any],
    schema_valid: bool,
    schema_errors: list[str],
) -> dict[str, Any]:
    """
    Compute the final score based on trajectory and ground truth.

    Args:
        trajectory: Agent trajectory data.
        ground_truth: Ground truth data.
        schema_valid: Whether trajectory passed schema validation.
        schema_errors: List of schema validation errors.

    Returns:
        Score dictionary in Harbor reward.json format.
    """
    # If schema validation failed, penalize score
    if not schema_valid:
        return {
            "score": 0.0,
            "metrics": {
                "schema_valid": False,
                "schema_errors": schema_errors,
            },
            "error": "Trajectory failed schema validation",
        }

    # Compute requirement-based score
    req_score = compute_requirement_score(trajectory, ground_truth)

    result = {
        "score": req_score["score"],
        "metrics": {
            "schema_valid": True,
            "total_requirements": req_score["total_requirements"],
            "met_requirements": req_score["met_requirements"],
            "requirement_scores": req_score["requirement_scores"],
            "total_steps": len(trajectory.get("steps", [])),
        },
    }

    # Add completion status
    final_state = trajectory.get("final_state", {})
    if final_state.get("completed", False):
        result["metrics"]["task_completed"] = True
    else:
        result["metrics"]["task_completed"] = False

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="DevAI Trajectory Verifier")
    parser.add_argument(
        "--trajectory",
        required=True,
        help="Path to trajectory JSON file",
    )
    parser.add_argument(
        "--schema",
        required=True,
        help="Path to trajectory schema JSON",
    )
    parser.add_argument(
        "--ground-truth",
        required=True,
        help="Path to ground truth JSON",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to output reward JSON",
    )
    args = parser.parse_args()

    trajectory_path = Path(args.trajectory)
    schema_path = Path(args.schema)
    ground_truth_path = Path(args.ground_truth)
    output_path = Path(args.output)

    # Read ground truth
    if not ground_truth_path.exists():
        result = {"score": 0.0, "error": f"Ground truth not found: {ground_truth_path}"}
        output_path.write_text(json.dumps(result, indent=2))
        print(f"Error: {result['error']}")
        return

    with open(ground_truth_path, "r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    # Read schema
    if not schema_path.exists():
        result = {"score": 0.0, "error": f"Schema not found: {schema_path}"}
        output_path.write_text(json.dumps(result, indent=2))
        print(f"Error: {result['error']}")
        return

    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)

    # Read trajectory
    if not trajectory_path.exists():
        print(f"Warning: Trajectory file not found: {trajectory_path}")
        result = {
            "score": 0.0,
            "metrics": {
                "schema_valid": False,
                "total_requirements": len(ground_truth.get("requirements", [])),
                "met_requirements": 0,
            },
            "error": "No trajectory file found",
        }
        output_path.write_text(json.dumps(result, indent=2))
        return

    try:
        with open(trajectory_path, "r", encoding="utf-8") as f:
            trajectory = json.load(f)
    except json.JSONDecodeError as e:
        result = {"score": 0.0, "error": f"Invalid trajectory JSON: {e}"}
        output_path.write_text(json.dumps(result, indent=2))
        print(f"Error: {result['error']}")
        return

    # Validate trajectory against schema
    schema_valid, schema_errors = validate_trajectory_schema(trajectory, schema)

    # Compute score
    result = compute_score(trajectory, ground_truth, schema_valid, schema_errors)

    # Write output
    output_path.write_text(json.dumps(result, indent=2))

    print(f"Evaluation complete:")
    print(f"  Score: {result['score']}")
    if "metrics" in result:
        metrics = result["metrics"]
        print(f"  Schema valid: {metrics.get('schema_valid', 'N/A')}")
        print(f"  Requirements: {metrics.get('met_requirements', 0)}/{metrics.get('total_requirements', 0)}")
        print(f"  Total steps: {metrics.get('total_steps', 0)}")


if __name__ == "__main__":
    main()
