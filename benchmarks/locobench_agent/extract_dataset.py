#!/usr/bin/env python3
"""
Extract LoCoBench-Agent scenarios into normalized JSONL format.

Reads all JSON files from data/output/scenarios/*.json and outputs
normalized JSONL with key fields for task selection and evaluation.
"""

import json
import sys
from pathlib import Path
from typing import Any


def parse_language_from_id(scenario_id: str) -> str:
    """Extract programming language from scenario ID prefix.

    Scenario IDs follow the pattern:
    {language}_{domain}_{complexity}_{project_num}_{task_category}_{difficulty}_{variant}

    Example: python_api_gateway_expert_045_bug_investigation_hard_01 -> python
    """
    parts = scenario_id.split("_")
    if parts:
        return parts[0]
    return "unknown"


def extract_scenario(data: dict[str, Any]) -> dict[str, Any]:
    """Extract and normalize fields from a scenario JSON.

    Args:
        data: Raw scenario JSON data

    Returns:
        Normalized scenario dict with required fields
    """
    scenario_id = data.get("id", "")

    # Extract files_count from metadata, fall back to counting context_files
    metadata = data.get("metadata", {})
    files_count = metadata.get("files_count", 0)
    if files_count == 0:
        context_files = data.get("context_files", [])
        files_count = len(context_files) if isinstance(context_files, list) else 0

    return {
        "id": scenario_id,
        "task_category": data.get("task_category", ""),
        "difficulty": data.get("difficulty", ""),
        "title": data.get("title", ""),
        "context_length": data.get("context_length", 0),
        "files_count": files_count,
        "task_prompt": data.get("task_prompt", ""),
        "ground_truth": data.get("ground_truth", ""),
        "evaluation_criteria": data.get("evaluation_criteria", []),
        "language": parse_language_from_id(scenario_id),
    }


def main() -> int:
    """Main entry point for dataset extraction."""
    # Determine paths relative to this script
    script_dir = Path(__file__).parent
    scenarios_dir = script_dir / "data" / "output" / "scenarios"
    output_file = script_dir / "locobench_dataset.jsonl"

    if not scenarios_dir.exists():
        print(f"Error: Scenarios directory not found: {scenarios_dir}", file=sys.stderr)
        return 1

    # Find all JSON files
    scenario_files = sorted(scenarios_dir.glob("*.json"))

    if not scenario_files:
        print(f"Error: No JSON files found in {scenarios_dir}", file=sys.stderr)
        return 1

    print(f"Found {len(scenario_files)} scenario files")

    # Process each scenario
    extracted = []
    errors = 0

    for scenario_file in scenario_files:
        try:
            with open(scenario_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            normalized = extract_scenario(data)
            extracted.append(normalized)

        except json.JSONDecodeError as e:
            print(f"Warning: Failed to parse {scenario_file.name}: {e}", file=sys.stderr)
            errors += 1
        except Exception as e:
            print(f"Warning: Error processing {scenario_file.name}: {e}", file=sys.stderr)
            errors += 1

    # Write output JSONL
    with open(output_file, "w", encoding="utf-8") as f:
        for scenario in extracted:
            f.write(json.dumps(scenario, ensure_ascii=False) + "\n")

    print(f"Extracted {len(extracted)} scenarios to {output_file}")
    if errors > 0:
        print(f"Encountered {errors} errors during extraction")

    # Summary statistics
    categories = {}
    languages = {}
    for s in extracted:
        cat = s["task_category"]
        lang = s["language"]
        categories[cat] = categories.get(cat, 0) + 1
        languages[lang] = languages.get(lang, 0) + 1

    print("\nTask categories:")
    for cat, count in sorted(categories.items()):
        print(f"  {cat}: {count}")

    print("\nLanguages:")
    for lang, count in sorted(languages.items()):
        print(f"  {lang}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
