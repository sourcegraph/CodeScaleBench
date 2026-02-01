#!/usr/bin/env python3
"""
Generate a Harbor registry file for DI-Bench tasks.

This creates a registry.json file that can be used with Harbor's
--registry option to treat DI-Bench tasks as a dataset.
"""

import argparse
import json
from pathlib import Path


def generate_registry(tasks_dir: Path, output_path: Path, base_url: str = None):
    """Generate registry file from tasks directory."""
    tasks_dir = Path(tasks_dir).resolve()

    if not tasks_dir.exists():
        raise FileNotFoundError(f"Tasks directory not found: {tasks_dir}")

    # Find all task directories (they should have task.toml)
    task_dirs = [
        d for d in tasks_dir.iterdir()
        if d.is_dir() and (d / "task.toml").exists()
    ]

    if not task_dirs:
        raise ValueError(f"No valid task directories found in {tasks_dir}")

    # Determine git_url (local file path or provided URL)
    if base_url:
        git_url = base_url
    else:
        # Use file:// URL for local development
        git_url = f"file://{tasks_dir.parent.parent.parent}"

    # Group tasks by language
    languages = {}
    for task_dir in task_dirs:
        # Task names are like: python-instance-001
        parts = task_dir.name.split('-', 1)
        if len(parts) >= 2:
            lang = parts[0]
            if lang not in languages:
                languages[lang] = []

            # Relative path from harbor repo root
            rel_path = task_dir.relative_to(tasks_dir.parent.parent.parent)

            languages[lang].append({
                "name": task_dir.name,
                "git_url": git_url,
                "path": str(rel_path)
            })

    # Create registry entries (one per language)
    registry = []
    for lang, tasks in sorted(languages.items()):
        registry.append({
            "name": f"dibench-{lang}",
            "version": "1.0",
            "description": f"DI-Bench dependency inference tasks for {lang.upper()}",
            "tasks": tasks
        })

    # Also create an "all" version
    all_tasks = []
    for tasks in languages.values():
        all_tasks.extend(tasks)

    registry.append({
        "name": "dibench",
        "version": "1.0",
        "description": "DI-Bench: Dependency Inference Benchmark (all languages)",
        "tasks": all_tasks
    })

    # Write registry file
    output_path = Path(output_path)
    with open(output_path, 'w') as f:
        json.dump(registry, f, indent=4)

    print(f"✓ Generated registry with {len(all_tasks)} tasks")
    print(f"  Languages: {', '.join(sorted(languages.keys()))}")
    print(f"  Output: {output_path}")
    print()
    print("Usage:")
    print(f"  harbor datasets list --registry {output_path}")
    print(f"  harbor run --dataset dibench@1.0 --registry {output_path}")

    return registry


def main():
    parser = argparse.ArgumentParser(
        description="Generate Harbor registry for DI-Bench tasks"
    )
    parser.add_argument(
        "--tasks_dir",
        type=Path,
        required=True,
        help="Directory containing generated DI-Bench tasks"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default="dibench-registry.json",
        help="Output registry file path"
    )
    parser.add_argument(
        "--base_url",
        type=str,
        default=None,
        help="Base git URL (default: local file://)"
    )

    args = parser.parse_args()

    try:
        generate_registry(args.tasks_dir, args.output, args.base_url)
    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
