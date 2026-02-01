#!/usr/bin/env python3
"""
Verifier for RepoQA SR-QA tasks.

Extracts JSON output from agent and scores against ground truth.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from verifiers import SemanticRetrievalQAVerifier


def extract_json_from_text(text: str) -> Dict[str, Any] | None:
    """Extract JSON object from agent output text."""
    # Try to find JSON block in markdown code fence
    json_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Try to find raw JSON object
    # Start from first { and find matching }
    start_idx = text.find('{')
    if start_idx == -1:
        return None
    
    depth = 0
    end_idx = start_idx
    in_string = False
    escape_next = False
    
    for i in range(start_idx, len(text)):
        char = text[i]
        
        if escape_next:
            escape_next = False
            continue
        
        if char == '\\':
            escape_next = True
            continue
        
        if char == '"':
            in_string = not in_string
            continue
        
        if not in_string:
            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    end_idx = i + 1
                    break
    
    if end_idx > start_idx:
        try:
            return json.loads(text[start_idx:end_idx])
        except json.JSONDecodeError:
            pass
    
    return None


def verify():
    """Main verifier function."""
    # Read ground truth from file
    ground_truth_path = Path("/app/tests/ground_truth.json")
    
    if not ground_truth_path.exists():
        print(json.dumps({
            "correct_function": 0.0,
            "correct_path": 0.0,
            "justification_score": 0.0,
            "reasoning": "Ground truth file not found"
        }))
        return
    
    with open(ground_truth_path) as f:
        ground_truth = json.load(f)
    
    # Read agent output from stdin
    try:
        agent_output_text = sys.stdin.read()
    except Exception as e:
        print(json.dumps({
            "correct_function": 0.0,
            "correct_path": 0.0,
            "justification_score": 0.0,
            "reasoning": f"Failed to read agent output: {e}"
        }))
        return
    
    # Extract JSON from agent output
    agent_output = extract_json_from_text(agent_output_text)
    
    if agent_output is None:
        print(json.dumps({
            "correct_function": 0.0,
            "correct_path": 0.0,
            "justification_score": 0.0,
            "reasoning": "No valid JSON found in agent output"
        }))
        return
    
    # Verify using the appropriate verifier
    try:
        task_variant = ground_truth.get("task_variant", "sr-qa")
        
        if task_variant == "sr-qa":
            verifier = SemanticRetrievalQAVerifier(ground_truth)
        else:
            print(json.dumps({
                "correct_function": 0.0,
                "correct_path": 0.0,
                "justification_score": 0.0,
                "reasoning": f"Unknown task variant: {task_variant}"
            }))
            return
        
        result = verifier.verify(agent_output)
        
        # Convert to Harbor format (numeric rewards)
        output = {
            "correct_function": float(result.correct_function),
            "correct_path": float(result.correct_path),
            "justification_score": float(result.justification_score),
            "reasoning": float(result.justification_score),  # Use a numeric value for Harbor
        }
        
        print(json.dumps(output))
    
    except Exception as e:
        print(json.dumps({
            "correct_function": 0.0,
            "correct_path": 0.0,
            "justification_score": 0.0,
            "reasoning": f"Verification error: {e}"
        }))


if __name__ == "__main__":
    verify()
