"""
SWE-Perf data model, loader, and adapter.

SWE-Perf is a performance-focused benchmark measuring code optimization abilities.
It evaluates agents on their ability to optimize Python code for runtime performance.
The benchmark contains 140 instances from real Python repositories with focus on
functions that can be optimized for better runtime.

Key concepts:
- target_function: The function to optimize
- baseline_runtime: The original runtime to improve upon
- human_solution_reference: Reference to how humans optimized the function
- runtime_reduction: Primary metric measuring performance improvement

The adapter generates thin wrapper tasks for Harbor that delegate to SWE-Perf's
existing evaluation infrastructure. The verifier measures runtime reduction
as the primary scoring metric.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json


@dataclass
class SWEPerfTask:
    """
    Data model for a SWE-Perf task instance.

    SWE-Perf focuses on performance optimization of Python code. Each task
    targets a specific function that can be optimized for better runtime.

    Attributes:
        id: Unique task identifier (e.g., 'sweperf-001', 'repo__func_name')
        repo_name: Name of the source repository (e.g., 'numpy', 'scikit-learn')
        target_function: The function to be optimized (fully qualified name)
        human_solution_reference: Reference to how humans optimized this function
        baseline_runtime: The original runtime in seconds (for comparison)
        description: Brief description of what the function does
        difficulty: Task difficulty (easy, medium, hard)
        file_path: Path to the file containing the target function
        test_command: Command to run benchmarks/tests
        optimization_hints: Optional hints about optimization strategies
        metadata: Additional task metadata
    """

    id: str
    repo_name: str
    target_function: str
    human_solution_reference: str
    baseline_runtime: float
    description: str = ""
    difficulty: str = "medium"
    file_path: str = ""
    test_command: str = ""
    optimization_hints: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize values after initialization."""
        # Normalize difficulty to lowercase
        self.difficulty = self.difficulty.lower()

        # Ensure id is set - generate from repo and function if not provided
        if not self.id:
            # Create ID from repo_name and target_function
            func_safe = self.target_function.replace(".", "_").replace("/", "_")
            self.id = f"{self.repo_name}__{func_safe}"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "repo_name": self.repo_name,
            "target_function": self.target_function,
            "human_solution_reference": self.human_solution_reference,
            "baseline_runtime": self.baseline_runtime,
            "description": self.description,
            "difficulty": self.difficulty,
            "file_path": self.file_path,
            "test_command": self.test_command,
            "optimization_hints": self.optimization_hints,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SWEPerfTask":
        """Create a SWEPerfTask from a dictionary."""
        return cls(
            id=data.get("id", ""),
            repo_name=data.get("repo_name", data.get("repo", "")),
            target_function=data.get("target_function", data.get("function", "")),
            human_solution_reference=data.get(
                "human_solution_reference",
                data.get("human_solution", data.get("reference", "")),
            ),
            baseline_runtime=float(data.get("baseline_runtime", data.get("baseline", 0.0))),
            description=data.get("description", ""),
            difficulty=data.get("difficulty", "medium"),
            file_path=data.get("file_path", data.get("path", "")),
            test_command=data.get("test_command", data.get("test_cmd", "")),
            optimization_hints=data.get("optimization_hints", data.get("hints", [])),
            metadata=data.get("metadata", {}),
        )

    def get_expected_speedup(self) -> float:
        """
        Get expected speedup factor (if available in metadata).

        Returns:
            Expected speedup multiplier (e.g., 2.0 for 2x faster).
        """
        return float(self.metadata.get("expected_speedup", 1.5))

    def get_optimization_category(self) -> str:
        """
        Get optimization category (algorithmic, vectorization, etc.).

        Returns:
            Category string describing the type of optimization needed.
        """
        return str(self.metadata.get("optimization_category", "general"))


class SWEPerfLoader:
    """
    Loader for SWE-Perf task instances.

    Reads tasks from the SWE-Perf dataset structure. Supports loading from
    a manifest file, combined JSON file, or individual task files.

    Expected directory structure:
        data_dir/
        ├── tasks.json          (combined file with all 140 instances)
        └── instances/          (or individual task files)
            ├── instance_001.json
            └── ...

    Alternative manifest structure:
        data_dir/
        ├── manifest.json
        └── tasks/
            └── ...
    """

    def __init__(self, data_dir: str | Path | None = None) -> None:
        """
        Initialize the loader.

        Args:
            data_dir: Path to the SWE-Perf data directory.
                      If None, uses default path relative to this module.
        """
        if data_dir is None:
            # Default to a data directory relative to this module
            self.data_dir = Path(__file__).parent / "data"
        else:
            self.data_dir = Path(data_dir)

        self._tasks: list[SWEPerfTask] = []
        self._loaded = False

    def load(self) -> list[SWEPerfTask]:
        """
        Load all tasks from the data directory.

        Attempts to load from:
        1. tasks.json (combined file)
        2. manifest.json (manifest-based loading)
        3. instances/ directory with individual JSON files

        Returns:
            List of all SWEPerfTask objects.
        """
        if self._loaded:
            return self._tasks

        self._tasks = []

        # Try loading from combined tasks.json
        tasks_file = self.data_dir / "tasks.json"
        if tasks_file.exists():
            self._load_from_combined_file(tasks_file)
        # Try loading from manifest
        elif (self.data_dir / "manifest.json").exists():
            self._load_from_manifest(self.data_dir / "manifest.json")
        # Load from instances directory
        elif (self.data_dir / "instances").exists():
            self._load_from_instances_dir(self.data_dir / "instances")
        # Load from individual JSON files in data_dir
        elif self.data_dir.exists():
            self._load_from_json_files(self.data_dir)

        self._loaded = True
        return self._tasks

    def _load_from_combined_file(self, tasks_file: Path) -> None:
        """Load tasks from a single combined JSON file."""
        try:
            with open(tasks_file, encoding="utf-8") as f:
                data = json.load(f)

            # Handle both array of tasks and object with 'tasks' or 'instances' key
            tasks_data: list[dict[str, Any]]
            if isinstance(data, list):
                tasks_data = data
            elif isinstance(data, dict):
                tasks_or_instances = data.get("tasks", data.get("instances"))
                tasks_data = tasks_or_instances if tasks_or_instances is not None else []
            else:
                return

            for task_data in tasks_data:
                try:
                    task = SWEPerfTask.from_dict(task_data)
                    self._tasks.append(task)
                except (KeyError, TypeError, ValueError) as e:
                    print(f"Warning: Failed to parse task: {e}")

        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to load tasks.json: {e}")

    def _load_from_manifest(self, manifest_path: Path) -> None:
        """Load tasks from a manifest file."""
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)

            instances_list = manifest.get("instances", manifest.get("tasks", []))

            for instance_entry in instances_list:
                # Handle both string (task_id) and dict (full task data)
                if isinstance(instance_entry, str):
                    # Try to load from instances directory
                    instance_path = self.data_dir / "instances" / f"{instance_entry}.json"
                    if not instance_path.exists():
                        instance_path = self.data_dir / "tasks" / f"{instance_entry}.json"

                    if instance_path.exists():
                        task = self._load_task_file(instance_path)
                        if task:
                            self._tasks.append(task)
                elif isinstance(instance_entry, dict):
                    task = SWEPerfTask.from_dict(instance_entry)
                    self._tasks.append(task)

        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to load manifest: {e}")

    def _load_from_instances_dir(self, instances_dir: Path) -> None:
        """Load tasks from instances directory."""
        for json_file in sorted(instances_dir.glob("*.json")):
            task = self._load_task_file(json_file)
            if task:
                self._tasks.append(task)

    def _load_from_json_files(self, data_dir: Path) -> None:
        """Load tasks from individual JSON files in data directory."""
        for json_file in sorted(data_dir.glob("*.json")):
            if json_file.name in ("manifest.json", "tasks.json"):
                continue
            task = self._load_task_file(json_file)
            if task:
                self._tasks.append(task)

    def _load_task_file(self, file_path: Path) -> SWEPerfTask | None:
        """
        Load a single task from a JSON file.

        Args:
            file_path: Path to the task JSON file.

        Returns:
            SWEPerfTask if successful, None otherwise.
        """
        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            # If id not in data, use filename
            if "id" not in data:
                data["id"] = file_path.stem

            return SWEPerfTask.from_dict(data)

        except (json.JSONDecodeError, IOError, ValueError) as e:
            print(f"Warning: Failed to load task from {file_path}: {e}")
            return None

    def all_ids(self) -> list[str]:
        """
        Get all task IDs.

        Returns:
            List of all task IDs in the loaded dataset.
        """
        if not self._loaded:
            self.load()
        return [task.id for task in self._tasks]

    def get_task(self, task_id: str) -> SWEPerfTask | None:
        """
        Get a specific task by ID.

        Args:
            task_id: The task ID to look up.

        Returns:
            The task if found, None otherwise.
        """
        if not self._loaded:
            self.load()
        for task in self._tasks:
            if task.id == task_id:
                return task
        return None

    def task_count(self) -> int:
        """
        Get total number of loaded tasks.

        Returns:
            Number of tasks loaded.
        """
        if not self._loaded:
            self.load()
        return len(self._tasks)

    def filter_by_repo(self, repo_name: str) -> list[SWEPerfTask]:
        """
        Filter tasks by repository name.

        Args:
            repo_name: Repository name to filter by.

        Returns:
            List of tasks from the specified repository.
        """
        if not self._loaded:
            self.load()
        repo_lower = repo_name.lower()
        return [
            task for task in self._tasks if task.repo_name.lower() == repo_lower
        ]

    def filter_by_difficulty(self, difficulty: str) -> list[SWEPerfTask]:
        """
        Filter tasks by difficulty level.

        Args:
            difficulty: Difficulty level (easy, medium, hard).

        Returns:
            List of tasks matching the difficulty.
        """
        if not self._loaded:
            self.load()
        difficulty_lower = difficulty.lower()
        return [
            task for task in self._tasks
            if task.difficulty.lower() == difficulty_lower
        ]

    def filter_by_baseline_runtime(
        self,
        min_runtime: float | None = None,
        max_runtime: float | None = None,
    ) -> list[SWEPerfTask]:
        """
        Filter tasks by baseline runtime range.

        Args:
            min_runtime: Minimum baseline runtime in seconds (inclusive).
            max_runtime: Maximum baseline runtime in seconds (inclusive).

        Returns:
            List of tasks within the runtime range.
        """
        if not self._loaded:
            self.load()

        result = []
        for task in self._tasks:
            if min_runtime is not None and task.baseline_runtime < min_runtime:
                continue
            if max_runtime is not None and task.baseline_runtime > max_runtime:
                continue
            result.append(task)

        return result

    def get_repos(self) -> list[str]:
        """
        Get unique repository names.

        Returns:
            Sorted list of unique repository names.
        """
        if not self._loaded:
            self.load()
        return sorted(set(task.repo_name for task in self._tasks))

    def get_statistics(self) -> dict[str, Any]:
        """
        Get dataset statistics.

        Returns:
            Dictionary with statistics about the dataset.
        """
        if not self._loaded:
            self.load()

        if not self._tasks:
            return {
                "total_tasks": 0,
                "repos": [],
                "difficulty_distribution": {},
            }

        runtimes = [t.baseline_runtime for t in self._tasks if t.baseline_runtime > 0]

        return {
            "total_tasks": len(self._tasks),
            "repos": self.get_repos(),
            "repo_count": len(self.get_repos()),
            "difficulty_distribution": {
                "easy": len([t for t in self._tasks if t.difficulty == "easy"]),
                "medium": len([t for t in self._tasks if t.difficulty == "medium"]),
                "hard": len([t for t in self._tasks if t.difficulty == "hard"]),
            },
            "runtime_stats": {
                "min": min(runtimes) if runtimes else 0.0,
                "max": max(runtimes) if runtimes else 0.0,
                "avg": sum(runtimes) / len(runtimes) if runtimes else 0.0,
            },
        }


# Template directory for Harbor task generation
TEMPLATE_DIR = Path(__file__).parent / "templates"


class SWEPerfAdapter:
    """
    Thin wrapper adapter that generates Harbor-compatible tasks from SWE-Perf.

    This is a lightweight adapter that generates Harbor task metadata (task.toml,
    instruction.md) while delegating actual evaluation to SWE-Perf's existing
    infrastructure. The verifier wraps SWE-Perf's runtime measurement and outputs
    runtime_reduction as the primary metric.

    Generated Harbor task structure:
    - task.toml: Task configuration and metadata
    - instruction.md: Task instructions for the agent
    - environment/Dockerfile: Python environment with benchmarking tools
    - tests/test.sh: Verification script that wraps SWE-Perf evaluation
    - tests/verify.py: Computes runtime_reduction metric
    - tests/ground_truth.json: Reference data including baseline_runtime
    """

    NAME = "sweperf"

    def __init__(
        self,
        task_dir: str | Path,
        data_dir: str | Path | None = None,
    ) -> None:
        """
        Initialize the SWE-Perf adapter.

        Args:
            task_dir: Output directory for generated Harbor tasks.
            data_dir: Path to SWE-Perf data directory (optional).
        """
        self.task_dir = Path(task_dir)
        self.loader = SWEPerfLoader(data_dir)
        self.templates_dir = TEMPLATE_DIR

    def _render_template(self, template_path: Path, context: dict[str, Any]) -> str:
        """
        Simple template rendering by replacing {key} placeholders.

        Args:
            template_path: Path to the template file.
            context: Dictionary of placeholder values.

        Returns:
            Rendered template string.
        """
        content = template_path.read_text()
        for template_key, value in context.items():
            content = content.replace(f"{{{template_key}}}", str(value))
        return content

    def _generate_dockerfile(self, task: SWEPerfTask) -> str:
        """
        Generate Dockerfile for SWE-Perf tasks.

        Uses Python 3.10+ with performance benchmarking tools.

        Args:
            task: The SWEPerfTask instance.

        Returns:
            Dockerfile content as string.
        """
        return f"""FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \\
    build-essential \\
    curl \\
    git \\
    time \\
    jq \\
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager for fast installs
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Create working directories
RUN mkdir -p /workspace /tests /logs /benchmark

# Install benchmarking and profiling tools
RUN pip install --no-cache-dir \\
    pytest \\
    pytest-benchmark \\
    pyperf \\
    memory_profiler \\
    line_profiler \\
    numpy

# Copy repository/project files
# SWE-Perf tasks operate on specific repos
WORKDIR /workspace

# Set up benchmark environment
ENV BENCHMARK_ITERATIONS=10
ENV BENCHMARK_WARMUP=3

# Task-specific metadata
ENV TASK_ID="{task.id}"
ENV REPO_NAME="{task.repo_name}"
ENV TARGET_FUNCTION="{task.target_function}"
ENV BASELINE_RUNTIME="{task.baseline_runtime}"

CMD ["/bin/bash"]
"""

    def _generate_instruction(self, task: SWEPerfTask) -> str:
        """
        Generate instruction.md content.

        Args:
            task: The SWEPerfTask instance.

        Returns:
            Instruction content as string.
        """
        template_path = self.templates_dir / "instruction.md"

        # Format optimization hints
        hints_text = ""
        if task.optimization_hints:
            hints_text = "\n### Optimization Hints\n\n"
            for hint in task.optimization_hints:
                hints_text += f"- {hint}\n"

        # Build context
        context = {
            "id": task.id,
            "repo_name": task.repo_name,
            "target_function": task.target_function,
            "baseline_runtime": f"{task.baseline_runtime:.6f}",
            "description": task.description or f"Optimize the function {task.target_function}",
            "difficulty": task.difficulty,
            "file_path": task.file_path or "See repository structure",
            "human_solution_reference": task.human_solution_reference,
            "optimization_hints": hints_text,
            "test_command": task.test_command or "python -m pytest tests/ -v",
        }

        if template_path.exists():
            return self._render_template(template_path, context)

        # Fallback inline template
        return f"""# SWE-Perf Performance Optimization Task

## Overview

**Task ID**: {task.id}
**Repository**: {task.repo_name}
**Difficulty**: {task.difficulty}
**Target Function**: `{task.target_function}`
**Baseline Runtime**: {task.baseline_runtime:.6f} seconds

---

## Description

{task.description or f"Optimize the function `{task.target_function}` for better runtime performance."}

## Target Function

The function to optimize is located at:
- **File**: {task.file_path or "See repository structure"}
- **Function**: `{task.target_function}`

## Baseline Performance

The current baseline runtime is **{task.baseline_runtime:.6f} seconds**.
Your goal is to reduce this runtime while maintaining correctness.

{hints_text}

## Human Reference

For reference, here is how humans approached this optimization:
{task.human_solution_reference}

---

## Instructions

1. Analyze the target function and understand its purpose
2. Profile the code to identify bottlenecks
3. Apply optimizations (algorithmic improvements, vectorization, caching, etc.)
4. Ensure all existing tests pass
5. Benchmark your optimized solution

## Testing

Run the benchmarks with:
```bash
{task.test_command or "python -m pytest tests/ -v"}
```

## Output

Your optimized code should be in `/workspace/optimized/`.
The verifier will measure runtime improvement as:

```
runtime_reduction = 1 - (optimized_runtime / baseline_runtime)
```

Higher values indicate better optimization. A value of 0.5 means 2x speedup.

## Workspace Structure

```
/workspace/
├── original/          # Original code (read-only reference)
├── optimized/         # Your optimized implementation
├── tests/             # Test suite
└── benchmark_results.json  # Your benchmark output
```

## Tips

- Profile before optimizing to find the real bottlenecks
- Ensure correctness - optimization at the cost of correctness scores 0
- Consider algorithmic complexity first, then micro-optimizations
- Use NumPy/vectorization for numerical code where applicable
- Consider caching for repeated computations
"""

    def _generate_task_toml(self, task: SWEPerfTask) -> str:
        """
        Generate task.toml content.

        Args:
            task: The SWEPerfTask instance.

        Returns:
            Task configuration as TOML string.
        """
        template_path = self.templates_dir / "task.toml"

        # Format tags
        tags = [
            "sweperf",
            "performance",
            "optimization",
            task.difficulty,
            task.repo_name.lower().replace("-", "_"),
        ]
        tags_str = ", ".join(f'"{t}"' for t in tags)

        context = {
            "task_id": task.id,
            "repo_name": task.repo_name,
            "target_function": task.target_function,
            "baseline_runtime": f"{task.baseline_runtime:.6f}",
            "difficulty": task.difficulty,
            "tags": tags_str,
        }

        if template_path.exists():
            return self._render_template(template_path, context)

        # Fallback inline template
        return f"""version = "1.0"

[metadata]
author_name = "SWE-Perf Adapter"
author_email = "unknown"
task_id = "{task.id}"
repo_name = "{task.repo_name}"
target_function = "{task.target_function}"
baseline_runtime = {task.baseline_runtime}
difficulty = "{task.difficulty}"
tags = [{tags_str}]

[verifier]
timeout_sec = 600.0
command = "bash /tests/test.sh"
primary_metric = "runtime_reduction"

[agent]
timeout_sec = 3600.0
model_hint = "requires-mcp"

[environment]
build_timeout_sec = 300.0
cpus = 4
memory = "8G"
storage = "20G"
"""

    def _generate_test_sh(self, task: SWEPerfTask) -> str:
        """
        Generate test.sh verification script.

        Args:
            task: The SWEPerfTask instance.

        Returns:
            Shell script content.
        """
        return f"""#!/bin/bash
# SWE-Perf Verification Script
# Task: {task.id}
# Target: {task.target_function}

set -uo pipefail

echo "=== SWE-Perf Verifier ==="
echo "Task ID: {task.id}"
echo "Repository: {task.repo_name}"
echo "Target Function: {task.target_function}"
echo "Baseline Runtime: {task.baseline_runtime}"

# Create output directories
mkdir -p /logs/verifier

# Check for ground truth
if [ ! -f /tests/ground_truth.json ]; then
    echo "ERROR: ground_truth.json not found"
    echo '{{"score": 0.0, "error": "Missing ground truth", "runtime_reduction": 0.0}}' > /logs/verifier/reward.json
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

# Check for optimized code
OPTIMIZED_DIR="/workspace/optimized"
if [ ! -d "$OPTIMIZED_DIR" ]; then
    echo "WARNING: Optimized directory not found, checking /workspace"
    OPTIMIZED_DIR="/workspace"
fi

# Look for benchmark results
BENCHMARK_RESULTS=""
for path in /workspace/benchmark_results.json /workspace/optimized/benchmark_results.json /logs/benchmark_results.json; do
    if [ -f "$path" ]; then
        BENCHMARK_RESULTS="$path"
        break
    fi
done

echo "Optimized code directory: $OPTIMIZED_DIR"
echo "Benchmark results file: $BENCHMARK_RESULTS"

# Run Python verifier to compute runtime_reduction
python3 /tests/verify.py \\
    --optimized-dir "$OPTIMIZED_DIR" \\
    --benchmark-results "$BENCHMARK_RESULTS" \\
    --ground-truth /tests/ground_truth.json \\
    --output /logs/verifier/reward.json \\
    2>&1 | tee /logs/verifier/verifier.log

# Extract score and write to reward.txt
if [ -f /logs/verifier/reward.json ]; then
    SCORE=$(python3 -c "import json; print(json.load(open('/logs/verifier/reward.json')).get('score', 0.0))" 2>/dev/null || echo "0.0")
    echo "$SCORE" > /logs/verifier/reward.txt
    echo "Verification complete. Score: $SCORE"
else
    echo "0.0" > /logs/verifier/reward.txt
    echo "Verification failed - no reward.json generated"
fi

# Always exit 0 for Harbor compatibility
exit 0
"""

    def _generate_verify_py(self, task: SWEPerfTask) -> str:
        """
        Generate verify.py for computing runtime_reduction metric.

        Args:
            task: The SWEPerfTask instance.

        Returns:
            Python script content.
        """
        return '''#!/usr/bin/env python3
"""
SWE-Perf Verifier

Evaluates agent output by measuring runtime reduction compared to baseline.
The primary metric is runtime_reduction = 1 - (optimized_runtime / baseline_runtime).
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def run_benchmark(
    optimized_dir: Path,
    ground_truth: dict[str, Any],
    iterations: int = 10,
) -> dict[str, Any]:
    """
    Run benchmark on the optimized code.

    This is a simplified benchmark runner. In production, this would
    delegate to SWE-Perf's actual benchmark infrastructure.

    Args:
        optimized_dir: Directory containing optimized code.
        ground_truth: Ground truth data with baseline runtime.
        iterations: Number of benchmark iterations.

    Returns:
        Benchmark results dictionary.
    """
    baseline_runtime = ground_truth.get("baseline_runtime", 0.0)
    target_function = ground_truth.get("target_function", "")

    # For now, return a placeholder - actual implementation would run benchmarks
    # This wrapper allows SWE-Perf's evaluation to be plugged in
    return {
        "baseline_runtime": baseline_runtime,
        "optimized_runtime": None,  # To be measured
        "target_function": target_function,
        "iterations": iterations,
        "status": "pending_measurement",
    }


def evaluate_runtime(
    benchmark_results: dict[str, Any] | None,
    ground_truth: dict[str, Any],
) -> dict[str, Any]:
    """
    Evaluate runtime reduction from benchmark results.

    Args:
        benchmark_results: Benchmark results from agent or verifier.
        ground_truth: Ground truth with baseline runtime.

    Returns:
        Evaluation result dictionary with runtime_reduction as primary metric.
    """
    baseline_runtime = ground_truth.get("baseline_runtime", 0.0)

    if baseline_runtime <= 0:
        return {
            "score": 0.0,
            "runtime_reduction": 0.0,
            "error": "Invalid baseline runtime",
            "metrics": {},
        }

    # If no benchmark results provided, check for agent-provided results
    if benchmark_results is None:
        return {
            "score": 0.0,
            "runtime_reduction": 0.0,
            "note": "No benchmark results provided",
            "metrics": {
                "baseline_runtime": baseline_runtime,
                "optimized_runtime": None,
            },
        }

    # Get optimized runtime from results
    optimized_runtime = benchmark_results.get(
        "optimized_runtime",
        benchmark_results.get("runtime", benchmark_results.get("mean_time")),
    )

    # Check if tests passed (correctness check)
    tests_passed = benchmark_results.get("tests_passed", True)
    if isinstance(tests_passed, int):
        tests_total = benchmark_results.get("tests_total", tests_passed)
        tests_passed = tests_passed >= tests_total if tests_total > 0 else True

    if not tests_passed:
        return {
            "score": 0.0,
            "runtime_reduction": 0.0,
            "error": "Tests failed - correctness not verified",
            "metrics": {
                "baseline_runtime": baseline_runtime,
                "optimized_runtime": optimized_runtime,
                "tests_passed": False,
            },
        }

    if optimized_runtime is None:
        return {
            "score": 0.0,
            "runtime_reduction": 0.0,
            "note": "No optimized runtime in benchmark results",
            "metrics": {
                "baseline_runtime": baseline_runtime,
            },
        }

    # Compute runtime reduction
    # runtime_reduction = 1 - (optimized / baseline)
    # 0.0 = no improvement, 0.5 = 2x speedup, 0.9 = 10x speedup
    if optimized_runtime <= 0:
        runtime_reduction = 0.0
    else:
        runtime_reduction = 1.0 - (optimized_runtime / baseline_runtime)

    # Clamp to valid range [0, 1]
    runtime_reduction = max(0.0, min(1.0, runtime_reduction))

    # Use runtime_reduction as the score
    score = runtime_reduction

    # Calculate speedup factor for informational purposes
    speedup = baseline_runtime / optimized_runtime if optimized_runtime > 0 else 0.0

    return {
        "score": round(score, 4),
        "runtime_reduction": round(runtime_reduction, 4),
        "metrics": {
            "baseline_runtime": baseline_runtime,
            "optimized_runtime": optimized_runtime,
            "speedup": round(speedup, 2),
            "tests_passed": tests_passed,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="SWE-Perf Verifier")
    parser.add_argument(
        "--optimized-dir",
        help="Path to optimized code directory",
    )
    parser.add_argument(
        "--benchmark-results",
        help="Path to benchmark results JSON (optional)",
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

    # Read benchmark results if provided
    benchmark_results = None
    if args.benchmark_results and args.benchmark_results != "":
        benchmark_path = Path(args.benchmark_results)
        if benchmark_path.exists():
            try:
                with open(benchmark_path, "r", encoding="utf-8") as f:
                    benchmark_results = json.load(f)
            except json.JSONDecodeError as e:
                print(f"Warning: Failed to parse benchmark results: {e}")

    # Evaluate
    result = evaluate_runtime(benchmark_results, ground_truth)

    # Write output
    output_path.write_text(json.dumps(result, indent=2))

    print(f"Evaluation complete:")
    print(f"  Score: {result.get('score', 0.0)}")
    print(f"  Runtime Reduction: {result.get('runtime_reduction', 0.0)}")
    metrics = result.get("metrics", {})
    if metrics:
        print(f"  Baseline: {metrics.get('baseline_runtime', 'N/A')}s")
        print(f"  Optimized: {metrics.get('optimized_runtime', 'N/A')}s")
        print(f"  Speedup: {metrics.get('speedup', 'N/A')}x")


if __name__ == "__main__":
    main()
'''

    def _create_ground_truth(self, task: SWEPerfTask) -> dict[str, Any]:
        """
        Create ground truth JSON for verification.

        Args:
            task: The SWEPerfTask instance.

        Returns:
            Ground truth dictionary.
        """
        return {
            "task_id": task.id,
            "repo_name": task.repo_name,
            "target_function": task.target_function,
            "baseline_runtime": task.baseline_runtime,
            "human_solution_reference": task.human_solution_reference,
            "file_path": task.file_path,
            "difficulty": task.difficulty,
            "optimization_hints": task.optimization_hints,
            "test_command": task.test_command,
            "metadata": task.metadata,
        }

    def generate_task(self, task_id: str, local_task_id: str | None = None) -> Path:
        """
        Generate a Harbor task directory for a SWE-Perf task.

        Args:
            task_id: SWE-Perf task ID.
            local_task_id: Optional local directory name for the task.
                          Defaults to task_id if not provided.

        Returns:
            Path to the generated task directory.

        Raises:
            ValueError: If task not found.
        """
        # Load the task
        self.loader.load()
        task = self.loader.get_task(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")

        # Determine output directory
        out_dir_name = local_task_id if local_task_id else task_id
        out_dir = self.task_dir / out_dir_name
        out_dir.mkdir(parents=True, exist_ok=True)

        # Create directory structure
        environment_dir = out_dir / "environment"
        tests_dir = out_dir / "tests"
        environment_dir.mkdir(parents=True, exist_ok=True)
        tests_dir.mkdir(parents=True, exist_ok=True)

        # 1. Generate instruction.md
        instruction_content = self._generate_instruction(task)
        (out_dir / "instruction.md").write_text(instruction_content)

        # 2. Generate task.toml
        task_toml_content = self._generate_task_toml(task)
        (out_dir / "task.toml").write_text(task_toml_content)

        # 3. Generate Dockerfile
        dockerfile_content = self._generate_dockerfile(task)
        (environment_dir / "Dockerfile").write_text(dockerfile_content)

        # 4. Generate test.sh
        test_sh_content = self._generate_test_sh(task)
        test_sh_path = tests_dir / "test.sh"
        test_sh_path.write_text(test_sh_content)
        test_sh_path.chmod(0o755)

        # 5. Generate verify.py
        verify_py_content = self._generate_verify_py(task)
        verify_py_path = tests_dir / "verify.py"
        verify_py_path.write_text(verify_py_content)
        verify_py_path.chmod(0o755)

        # 6. Write ground truth
        ground_truth = self._create_ground_truth(task)
        ground_truth_path = tests_dir / "ground_truth.json"
        with open(ground_truth_path, "w", encoding="utf-8") as f:
            json.dump(ground_truth, f, indent=2)

        return out_dir

    def generate_all_tasks(
        self,
        repo_filter: str | None = None,
        limit: int | None = None,
    ) -> list[Path]:
        """
        Generate Harbor tasks for all or filtered SWE-Perf tasks.

        Args:
            repo_filter: Optional repository name to filter by.
            limit: Optional limit on number of tasks to generate.

        Returns:
            List of paths to generated task directories.
        """
        self.loader.load()

        if repo_filter:
            tasks = self.loader.filter_by_repo(repo_filter)
        else:
            tasks = self.loader.load()

        if limit is not None and limit > 0:
            tasks = tasks[:limit]

        paths = []
        for task in tasks:
            try:
                path = self.generate_task(task.id)
                paths.append(path)
            except Exception as e:
                print(f"Warning: Failed to generate task {task.id}: {e}")

        return paths
