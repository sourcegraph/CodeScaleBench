#!/usr/bin/env python3
"""
Import TAC tasks into Harbor-compatible format.

This script:
1. Verifies TAC Docker images are available
2. Creates/updates Harbor task wrappers from TAC tasks
3. Generates task.toml, instruction.md, Dockerfile, and test.sh

Usage:
    python import_tac_tasks.py [--task TASK_ID] [--all] [--verify-images]

Examples:
    # Import all configured tasks
    python import_tac_tasks.py --all
    
    # Import a specific task
    python import_tac_tasks.py --task sde-implement-hyperloglog
    
    # Verify Docker images are available
    python import_tac_tasks.py --verify-images
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

# Base directory for this benchmark
BENCHMARK_DIR = Path(__file__).parent.parent
TEMPLATES_DIR = BENCHMARK_DIR / "templates"

# TAC Docker image registry
TAC_REGISTRY = "ghcr.io/theagentcompany"
TAC_VERSION = "1.0.0"

@dataclass
class TACTask:
    """Represents a TAC task configuration."""
    tac_id: str                    # Original TAC task ID (e.g., "sde-implement-hyperloglog")
    harbor_id: str                 # Our Harbor task ID (e.g., "tac-implement-hyperloglog")
    title: str                     # Human-readable title
    description: str               # Short description
    language: str                  # Primary language (python, cpp, go, etc.)
    difficulty: str                # easy, medium, hard
    mcp_value: str                 # Expected MCP value: low, medium, high, very-high
    grading_type: str              # deterministic, llm-based, mixed
    dependencies: list[str]        # TAC server dependencies (gitlab, rocketchat, etc.)

# Curated TAC tasks for MCP value evaluation
CURATED_TASKS = [
    TACTask(
        tac_id="sde-implement-hyperloglog",
        harbor_id="tac-implement-hyperloglog",
        title="Implement HyperLogLog Algorithm",
        description="Implement HyperLogLog in bustub database system",
        language="cpp",
        difficulty="hard",
        mcp_value="high",
        grading_type="deterministic",
        dependencies=["gitlab"],
    ),
    TACTask(
        tac_id="sde-implement-buffer-pool-manager-bustub",
        harbor_id="tac-buffer-pool-manager",
        title="Implement Buffer Pool Manager",
        description="Implement buffer pool manager in bustub",
        language="cpp",
        difficulty="hard",
        mcp_value="high",
        grading_type="deterministic",
        dependencies=["gitlab"],
    ),
    TACTask(
        tac_id="sde-dependency-change-1",
        harbor_id="tac-dependency-change",
        title="Update Dependency Versions",
        description="Update Python dependency versions in OpenHands",
        language="python",
        difficulty="medium",
        mcp_value="medium",
        grading_type="deterministic",
        dependencies=["gitlab"],
    ),
    TACTask(
        tac_id="sde-find-answer-in-codebase-1",
        harbor_id="tac-find-in-codebase-1",
        title="Find PR in Codebase (Context Window)",
        description="Find PR that improved llama3.1 context window",
        language="cpp",
        difficulty="medium",
        mcp_value="very-high",
        grading_type="llm-based",
        dependencies=["gitlab", "rocketchat"],
    ),
    TACTask(
        tac_id="sde-find-answer-in-codebase-2",
        harbor_id="tac-find-in-codebase-2",
        title="Find PR in Codebase (File Change)",
        description="Find PR that changed a specific file",
        language="cpp",
        difficulty="medium",
        mcp_value="very-high",
        grading_type="llm-based",
        dependencies=["gitlab", "rocketchat"],
    ),
    TACTask(
        tac_id="sde-copilot-arena-server-new-endpoint",
        harbor_id="tac-copilot-arena-endpoint",
        title="Add API Endpoint",
        description="Add new endpoint to copilot-arena-server",
        language="python",
        difficulty="medium",
        mcp_value="medium-high",
        grading_type="deterministic",
        dependencies=["gitlab"],
    ),
    TACTask(
        tac_id="sde-write-a-unit-test-for-search_file-function",
        harbor_id="tac-write-unit-test",
        title="Write Unit Test",
        description="Write unit test for search_file function",
        language="python",
        difficulty="medium",
        mcp_value="high",
        grading_type="deterministic",
        dependencies=["gitlab"],
    ),
    TACTask(
        tac_id="sde-troubleshoot-dev-setup",
        harbor_id="tac-troubleshoot-dev-setup",
        title="Troubleshoot Dev Setup",
        description="Fix broken development environment",
        language="python",
        difficulty="medium",
        mcp_value="medium",
        grading_type="mixed",
        dependencies=["gitlab", "rocketchat"],
    ),
]

def get_docker_image(tac_id: str) -> str:
    """Get the full Docker image name for a TAC task."""
    return f"{TAC_REGISTRY}/{tac_id}-image:{TAC_VERSION}"

def verify_docker_image(tac_id: str) -> bool:
    """Check if a Docker image exists (via docker manifest inspect)."""
    image = get_docker_image(tac_id)
    try:
        result = subprocess.run(
            ["docker", "manifest", "inspect", image],
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False

def pull_docker_image(tac_id: str) -> bool:
    """Pull a Docker image."""
    image = get_docker_image(tac_id)
    print(f"  Pulling {image}...")
    try:
        result = subprocess.run(
            ["docker", "pull", image],
            capture_output=True,
            text=True,
            timeout=300
        )
        if result.returncode == 0:
            print(f"  ✓ Successfully pulled {image}")
            return True
        else:
            print(f"  ✗ Failed to pull {image}: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        print(f"  ✗ Timeout pulling {image}")
        return False
    except FileNotFoundError:
        print("  ✗ Docker not found. Is Docker installed?")
        return False

def verify_all_images() -> dict:
    """Verify all curated TAC task images are available."""
    results = {}
    print("Verifying TAC Docker images...")
    print("-" * 60)
    
    for task in CURATED_TASKS:
        image = get_docker_image(task.tac_id)
        available = verify_docker_image(task.tac_id)
        results[task.tac_id] = available
        status = "✓" if available else "✗"
        print(f"  {status} {task.tac_id}")
    
    print("-" * 60)
    available_count = sum(results.values())
    total_count = len(results)
    print(f"Available: {available_count}/{total_count}")
    
    return results

def get_task_by_id(task_id: str) -> Optional[TACTask]:
    """Find a task by its TAC ID or Harbor ID."""
    for task in CURATED_TASKS:
        if task.tac_id == task_id or task.harbor_id == task_id:
            return task
    return None

def create_task_directory(task: TACTask, force: bool = False) -> bool:
    """Create a Harbor task directory for a TAC task."""
    task_dir = BENCHMARK_DIR / task.harbor_id
    
    if task_dir.exists() and not force:
        print(f"  Task directory already exists: {task.harbor_id}")
        print(f"  Use --force to overwrite")
        return True
    
    # Create directory structure
    (task_dir / "environment").mkdir(parents=True, exist_ok=True)
    (task_dir / "tests").mkdir(parents=True, exist_ok=True)
    
    print(f"  Created task directory: {task.harbor_id}")
    return True

def list_curated_tasks():
    """Print list of curated TAC tasks."""
    print("\nCurated TAC Tasks for MCP Value Evaluation")
    print("=" * 70)
    print(f"{'Harbor ID':<30} {'TAC ID':<40} {'MCP Value':<12}")
    print("-" * 70)
    
    for task in CURATED_TASKS:
        print(f"{task.harbor_id:<30} {task.tac_id:<40} {task.mcp_value:<12}")
    
    print("-" * 70)
    print(f"Total: {len(CURATED_TASKS)} tasks")
    print("\nTo run a task:")
    print("  harbor run --path benchmarks/tac_mcp_value/<task-id> \\")
    print("    --agent-import-path agents.mcp_variants:StrategicDeepSearchAgent \\")
    print("    --model anthropic/claude-haiku-4-5-20251001 -n 1")

def main():
    parser = argparse.ArgumentParser(
        description="Import TAC tasks into Harbor-compatible format"
    )
    parser.add_argument(
        "--task", "-t",
        help="Import specific task by TAC ID or Harbor ID"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Import all curated tasks"
    )
    parser.add_argument(
        "--verify-images", "-v",
        action="store_true",
        help="Verify Docker images are available"
    )
    parser.add_argument(
        "--pull",
        action="store_true",
        help="Pull Docker images if not available"
    )
    parser.add_argument(
        "--list", "-l",
        action="store_true",
        help="List all curated tasks"
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="Overwrite existing task directories"
    )
    
    args = parser.parse_args()
    
    if args.list:
        list_curated_tasks()
        return 0
    
    if args.verify_images:
        results = verify_all_images()
        
        if args.pull:
            print("\nPulling missing images...")
            for tac_id, available in results.items():
                if not available:
                    pull_docker_image(tac_id)
        
        return 0 if all(results.values()) else 1
    
    if args.task:
        task = get_task_by_id(args.task)
        if not task:
            print(f"Error: Task not found: {args.task}")
            print("Use --list to see available tasks")
            return 1
        
        print(f"Importing task: {task.harbor_id}")
        if args.pull:
            pull_docker_image(task.tac_id)
        create_task_directory(task, args.force)
        print(f"✓ Task imported: {task.harbor_id}")
        return 0
    
    if args.all:
        print(f"Importing all {len(CURATED_TASKS)} curated tasks...")
        for task in CURATED_TASKS:
            print(f"\n{task.harbor_id}:")
            if args.pull:
                pull_docker_image(task.tac_id)
            create_task_directory(task, args.force)
        print(f"\n✓ All tasks imported")
        return 0
    
    # Default: show help
    parser.print_help()
    return 0

if __name__ == "__main__":
    sys.exit(main())
