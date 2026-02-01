#!/usr/bin/env python3
"""
Extract agent JSON output from trajectory file.

This script reads the agent's trajectory and extracts the JSON answer
from the final message containing the solution.
"""

import json
import re
import sys
from pathlib import Path


def extract_json_from_text(text: str) -> dict | None:
    """Extract JSON object from agent output text."""
    # Try to find JSON block in markdown code fence
    json_match = re.search(r'```(?:json)?\s*\n(.*?)\n```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Try to find raw JSON object
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


def main():
    """Extract agent output from trajectory file."""
    
    trajectory_file = Path("/app/agent/trajectory.json")
    
    if not trajectory_file.exists():
        print("ERROR: Agent trajectory not found")
        sys.exit(1)
    
    try:
        with open(trajectory_file) as f:
            trajectory = json.load(f)
    except Exception as e:
        print(f"ERROR: Failed to read trajectory: {e}")
        sys.exit(1)
    
    # Find the last agent message that contains a JSON solution
    steps = trajectory.get('steps', [])
    
    agent_output = None
    for step in reversed(steps):
        if step.get('source') == 'agent':
            message = step.get('message', '')
            agent_output = extract_json_from_text(message)
            if agent_output:
                break
    
    if agent_output is None:
        print("ERROR: No JSON found in agent output")
        sys.exit(1)
    
    # Save to solution.json
    try:
        solution_file = Path("/app/solution.json")
        with open(solution_file, 'w') as f:
            json.dump(agent_output, f, indent=2)
        print(f"SUCCESS: Extracted solution to /app/solution.json")
    except Exception as e:
        print(f"ERROR: Failed to write solution.json: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
