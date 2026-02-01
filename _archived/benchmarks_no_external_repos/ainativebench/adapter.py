"""
AINativeBench data model and loader.

AINativeBench is a benchmark suite with 8 specialized benchmarks,
each having 4 variants for different evaluation modes.

Benchmarks:
- RepoBench: Repository-level code completion
- CrossCodeEval: Cross-file code evaluation
- RepoExec: Repository-level code execution
- SWE-bench: Software engineering problem solving
- DevBench: Developer benchmark tasks
- Cocomic: Code completion with context
- EvoCodeBench: Evolution-based code benchmark
- MdEval: Multi-document evaluation

Variants for each benchmark:
- easy: Basic difficulty tasks
- medium: Moderate difficulty tasks
- hard: Advanced difficulty tasks
- retrieval: Tasks requiring context retrieval
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json


# AINativeBench benchmark names
AINATIVEBENCH_BENCHMARKS = [
    "repobench",
    "crosscodeeval",
    "repoexec",
    "swe-bench",
    "devbench",
    "cocomic",
    "evocodebench",
    "mdeval",
]

# AINativeBench variants (4 per benchmark)
AINATIVEBENCH_VARIANTS = [
    "easy",
    "medium",
    "hard",
    "retrieval",
]


@dataclass
class ScoringMetrics:
    """Scoring metrics for an AINativeBench task."""

    primary_metric: str = "pass_rate"
    secondary_metrics: list[str] = field(default_factory=list)
    thresholds: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "primary_metric": self.primary_metric,
            "secondary_metrics": self.secondary_metrics,
            "thresholds": self.thresholds,
        }


@dataclass
class TestCase:
    """A test case for an AINativeBench task."""

    name: str
    input_data: dict[str, Any] = field(default_factory=dict)
    expected_output: dict[str, Any] = field(default_factory=dict)
    timeout_sec: int = 60

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "name": self.name,
            "input_data": self.input_data,
            "expected_output": self.expected_output,
            "timeout_sec": self.timeout_sec,
        }


@dataclass
class AINativeBenchTask:
    """
    Data model for an AINativeBench task.

    Attributes:
        id: Unique task identifier (e.g., 'repobench-easy-001')
        benchmark_name: Name of the parent benchmark (e.g., 'repobench')
        variant: Task variant (e.g., 'easy', 'medium', 'hard', 'retrieval')
        test_cases: List of test cases for evaluation
        scoring_metrics: Metrics used for scoring
        description: Human-readable task description
        language: Primary programming language
        context_files: Files providing context for the task
        ground_truth: Ground truth solution or expected output
        metadata: Additional task metadata
    """

    id: str
    benchmark_name: str
    variant: str
    test_cases: list[TestCase] = field(default_factory=list)
    scoring_metrics: ScoringMetrics = field(default_factory=ScoringMetrics)
    description: str = ""
    language: str = "python"
    context_files: list[str] = field(default_factory=list)
    ground_truth: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate task fields."""
        if self.benchmark_name and self.benchmark_name.lower() not in AINATIVEBENCH_BENCHMARKS:
            # Allow unknown benchmarks but issue no error - flexibility for extensions
            pass
        if self.variant and self.variant.lower() not in AINATIVEBENCH_VARIANTS:
            # Allow unknown variants but issue no error - flexibility for extensions
            pass

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "benchmark_name": self.benchmark_name,
            "variant": self.variant,
            "test_cases": [tc.to_dict() for tc in self.test_cases],
            "scoring_metrics": self.scoring_metrics.to_dict(),
            "description": self.description,
            "language": self.language,
            "context_files": self.context_files,
            "ground_truth": self.ground_truth,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AINativeBenchTask":
        """Create an AINativeBenchTask from a dictionary."""
        # Parse test cases
        test_cases_data = data.get("test_cases", [])
        test_cases = [
            TestCase(
                name=tc.get("name", f"test_{i}"),
                input_data=tc.get("input_data", {}),
                expected_output=tc.get("expected_output", {}),
                timeout_sec=tc.get("timeout_sec", 60),
            )
            for i, tc in enumerate(test_cases_data)
        ]

        # Parse scoring metrics
        metrics_data = data.get("scoring_metrics", {})
        scoring_metrics = ScoringMetrics(
            primary_metric=metrics_data.get("primary_metric", "pass_rate"),
            secondary_metrics=metrics_data.get("secondary_metrics", []),
            thresholds=metrics_data.get("thresholds", {}),
        )

        return cls(
            id=data.get("id", ""),
            benchmark_name=data.get("benchmark_name", ""),
            variant=data.get("variant", ""),
            test_cases=test_cases,
            scoring_metrics=scoring_metrics,
            description=data.get("description", ""),
            language=data.get("language", "python"),
            context_files=data.get("context_files", []),
            ground_truth=data.get("ground_truth", {}),
            metadata=data.get("metadata", {}),
        )


class AINativeBenchLoader:
    """
    Loader for AINativeBench tasks.

    Reads tasks from the AINativeBench dataset structure, which organizes
    tasks by benchmark and variant. Supports filtering by benchmark name
    and variant.

    Expected directory structure:
        data_dir/
        ├── repobench/
        │   ├── easy/
        │   │   ├── task_001.json
        │   │   └── task_002.json
        │   ├── medium/
        │   ├── hard/
        │   └── retrieval/
        ├── crosscodeeval/
        │   └── ...
        └── ...

    Alternative structure (flat with manifest):
        data_dir/
        ├── manifest.json
        └── tasks/
            ├── repobench-easy-001.json
            └── ...
    """

    def __init__(self, data_dir: str | Path | None = None) -> None:
        """
        Initialize the loader.

        Args:
            data_dir: Path to the AINativeBench data directory.
                      If None, uses default path.
        """
        if data_dir is None:
            # Default to a data directory relative to this module
            self.data_dir = Path(__file__).parent / "data"
        else:
            self.data_dir = Path(data_dir)

        self._tasks: list[AINativeBenchTask] = []
        self._loaded = False

    def load(self) -> list[AINativeBenchTask]:
        """
        Load all tasks from the data directory.

        Returns:
            List of all AINativeBenchTask objects.

        Raises:
            FileNotFoundError: If data directory doesn't exist and no tasks found.
        """
        if self._loaded:
            return self._tasks

        self._tasks = []

        # Try to load from manifest first
        manifest_path = self.data_dir / "manifest.json"
        if manifest_path.exists():
            self._load_from_manifest(manifest_path)
        elif self.data_dir.exists():
            # Load from hierarchical directory structure
            self._load_from_directory()

        # If no tasks loaded but directory exists, create empty list (valid state)
        # If directory doesn't exist and no manifest, that's OK - empty benchmark
        self._loaded = True
        return self._tasks

    def _load_from_manifest(self, manifest_path: Path) -> None:
        """Load tasks from a manifest file."""
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        tasks_dir = self.data_dir / "tasks"
        task_files = manifest.get("tasks", [])

        for task_file in task_files:
            task_path = tasks_dir / task_file
            if task_path.exists():
                task = self._load_task_file(task_path)
                if task:
                    self._tasks.append(task)

    def _load_from_directory(self) -> None:
        """Load tasks from hierarchical directory structure."""
        for benchmark in AINATIVEBENCH_BENCHMARKS:
            benchmark_dir = self.data_dir / benchmark
            if not benchmark_dir.exists():
                continue

            for variant in AINATIVEBENCH_VARIANTS:
                variant_dir = benchmark_dir / variant
                if not variant_dir.exists():
                    continue

                for task_file in variant_dir.glob("*.json"):
                    task = self._load_task_file(task_file, benchmark, variant)
                    if task:
                        self._tasks.append(task)

    def _load_task_file(
        self,
        task_path: Path,
        benchmark: str | None = None,
        variant: str | None = None,
    ) -> AINativeBenchTask | None:
        """Load a single task from a JSON file."""
        try:
            with open(task_path, encoding="utf-8") as f:
                data = json.load(f)

            # Override benchmark/variant if provided (from directory structure)
            if benchmark:
                data["benchmark_name"] = benchmark
            if variant:
                data["variant"] = variant

            # Generate ID if not present
            if not data.get("id"):
                stem = task_path.stem
                if benchmark and variant:
                    data["id"] = f"{benchmark}-{variant}-{stem}"
                else:
                    data["id"] = stem

            return AINativeBenchTask.from_dict(data)
        except (json.JSONDecodeError, KeyError) as e:
            # Log error but continue loading other tasks
            print(f"Warning: Failed to load task from {task_path}: {e}")
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

    def filter_by_benchmark(self, benchmark_name: str) -> list[AINativeBenchTask]:
        """
        Filter tasks by benchmark name.

        Args:
            benchmark_name: Name of the benchmark to filter by.

        Returns:
            List of tasks belonging to the specified benchmark.
        """
        if not self._loaded:
            self.load()
        benchmark_lower = benchmark_name.lower()
        return [
            task for task in self._tasks
            if task.benchmark_name.lower() == benchmark_lower
        ]

    def filter_by_variant(self, variant: str) -> list[AINativeBenchTask]:
        """
        Filter tasks by variant.

        Args:
            variant: Variant to filter by (e.g., 'easy', 'hard').

        Returns:
            List of tasks matching the specified variant.
        """
        if not self._loaded:
            self.load()
        variant_lower = variant.lower()
        return [
            task for task in self._tasks
            if task.variant.lower() == variant_lower
        ]

    def filter_by_benchmark_and_variant(
        self,
        benchmark_name: str,
        variant: str,
    ) -> list[AINativeBenchTask]:
        """
        Filter tasks by both benchmark name and variant.

        Args:
            benchmark_name: Name of the benchmark.
            variant: Variant to filter by.

        Returns:
            List of tasks matching both criteria.
        """
        if not self._loaded:
            self.load()
        benchmark_lower = benchmark_name.lower()
        variant_lower = variant.lower()
        return [
            task for task in self._tasks
            if task.benchmark_name.lower() == benchmark_lower
            and task.variant.lower() == variant_lower
        ]

    def get_task(self, task_id: str) -> AINativeBenchTask | None:
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

    def get_benchmarks(self) -> list[str]:
        """
        Get list of available benchmark names.

        Returns:
            List of unique benchmark names in the loaded dataset.
        """
        if not self._loaded:
            self.load()
        return list(set(task.benchmark_name for task in self._tasks))

    def get_variants(self) -> list[str]:
        """
        Get list of available variants.

        Returns:
            List of unique variants in the loaded dataset.
        """
        if not self._loaded:
            self.load()
        return list(set(task.variant for task in self._tasks))

    def task_count(self) -> int:
        """
        Get total number of loaded tasks.

        Returns:
            Number of tasks loaded.
        """
        if not self._loaded:
            self.load()
        return len(self._tasks)


# Template directory for Harbor task generation
TEMPLATE_DIR = Path(__file__).parent / "templates"


class AINativeBenchAdapter:
    """
    Adapter that converts AINativeBench tasks into Harbor task directories.

    Generates Harbor-compatible task structure with:
    - task.toml: Task configuration and metadata
    - instruction.md: Task instructions for the agent
    - environment/Dockerfile: Python 3.10+ with uv package manager
    - tests/test.sh: Verification script
    - tests/verify.py: Parses test_results/ JSON output to reward.json
    """

    NAME = "ainativebench"

    def __init__(
        self,
        task_dir: str | Path,
        data_dir: str | Path | None = None,
    ) -> None:
        """
        Initialize the AINativeBench adapter.

        Args:
            task_dir: Output directory for generated Harbor tasks.
            data_dir: Path to AINativeBench data directory (optional).
        """
        self.task_dir = Path(task_dir)
        self.loader = AINativeBenchLoader(data_dir)
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
        for key, value in context.items():
            # Handle {key} format
            content = content.replace(f"{{{key}}}", str(value))
        return content

    def _generate_dockerfile(self) -> str:
        """
        Generate Dockerfile for AINativeBench tasks.

        Uses Python 3.10+ with uv package manager as specified.

        Returns:
            Dockerfile content as string.
        """
        return """FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \\
    build-essential \\
    curl \\
    git \\
    jq \\
    && rm -rf /var/lib/apt/lists/*

# Install uv package manager
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Create working directories
RUN mkdir -p /app /logs /workspace /tests /test_results

# Set up Python environment with uv
WORKDIR /app

# Copy project files (if any)
COPY project /app/project

CMD ["/bin/bash"]
"""

    def _create_instruction(self, task: AINativeBenchTask) -> str:
        """
        Create instruction.md content for the task.

        Args:
            task: The AINativeBenchTask instance.

        Returns:
            Rendered instruction content.
        """
        template_path = self.templates_dir / "instruction.md"

        # Format test cases as markdown
        test_cases_text = ""
        if task.test_cases:
            test_cases_text = "### Test Cases\n\n"
            for i, tc in enumerate(task.test_cases, 1):
                test_cases_text += f"**Test {i}: {tc.name}**\n"
                if tc.input_data:
                    test_cases_text += f"- Input: `{json.dumps(tc.input_data)}`\n"
                if tc.expected_output:
                    test_cases_text += f"- Expected: `{json.dumps(tc.expected_output)}`\n"
                test_cases_text += f"- Timeout: {tc.timeout_sec}s\n\n"

        # Format scoring metrics
        metrics = task.scoring_metrics
        metrics_text = f"- Primary metric: {metrics.primary_metric}\n"
        if metrics.secondary_metrics:
            metrics_text += f"- Secondary metrics: {', '.join(metrics.secondary_metrics)}\n"
        if metrics.thresholds:
            for metric, threshold in metrics.thresholds.items():
                metrics_text += f"- {metric} threshold: {threshold}\n"

        # Format context files
        context_files_text = ""
        if task.context_files:
            context_files_text = "### Context Files\n\n"
            for f in task.context_files:
                context_files_text += f"- `{f}`\n"

        context = {
            "id": task.id,
            "benchmark_name": task.benchmark_name,
            "variant": task.variant,
            "language": task.language,
            "description": task.description,
            "test_cases": test_cases_text,
            "scoring_metrics": metrics_text,
            "context_files": context_files_text,
        }

        return self._render_template(template_path, context)

    def _create_task_toml(self, task: AINativeBenchTask) -> str:
        """
        Create task.toml content for the task.

        Args:
            task: The AINativeBenchTask instance.

        Returns:
            Task configuration as TOML string.
        """
        template_path = self.templates_dir / "task.toml"

        # Format tags
        tags = [
            "ainativebench",
            task.benchmark_name,
            task.variant,
            task.language,
        ]
        tags_str = ", ".join(f'"{t}"' for t in tags)

        context = {
            "task_id": task.id,
            "benchmark_name": task.benchmark_name,
            "variant": task.variant,
            "language": task.language,
            "primary_metric": task.scoring_metrics.primary_metric,
            "tags": tags_str,
            "num_test_cases": len(task.test_cases),
        }

        return self._render_template(template_path, context)

    def generate_task(self, task_id: str, local_task_id: str | None = None) -> Path:
        """
        Generate a Harbor task directory for an AINativeBench task.

        Args:
            task_id: AINativeBench task ID.
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
        instruction_content = self._create_instruction(task)
        (out_dir / "instruction.md").write_text(instruction_content)

        # 2. Generate task.toml
        task_toml_content = self._create_task_toml(task)
        (out_dir / "task.toml").write_text(task_toml_content)

        # 3. Generate Dockerfile
        dockerfile_content = self._generate_dockerfile()
        (environment_dir / "Dockerfile").write_text(dockerfile_content)

        # 4. Create empty project directory
        project_dir = environment_dir / "project"
        project_dir.mkdir(parents=True, exist_ok=True)

        # 5. Copy test.sh template
        test_sh_template = self.templates_dir / "test.sh"
        if test_sh_template.exists():
            test_sh_content = self._render_template(
                test_sh_template,
                {"id": task.id, "benchmark_name": task.benchmark_name},
            )
        else:
            # Generate default test.sh
            test_sh_content = self._generate_test_sh(task)
        test_sh_path = tests_dir / "test.sh"
        test_sh_path.write_text(test_sh_content)
        test_sh_path.chmod(0o755)

        # 6. Copy verify.py template
        verify_py_template = self.templates_dir / "verify.py"
        if verify_py_template.exists():
            verify_py_content = verify_py_template.read_text()
        else:
            # Generate default verify.py
            verify_py_content = self._generate_verify_py()
        verify_py_path = tests_dir / "verify.py"
        verify_py_path.write_text(verify_py_content)
        verify_py_path.chmod(0o755)

        # 7. Write ground truth
        ground_truth = {
            "task_id": task.id,
            "benchmark_name": task.benchmark_name,
            "variant": task.variant,
            "test_cases": [tc.to_dict() for tc in task.test_cases],
            "scoring_metrics": task.scoring_metrics.to_dict(),
            "ground_truth": task.ground_truth,
        }
        ground_truth_path = tests_dir / "ground_truth.json"
        with open(ground_truth_path, "w", encoding="utf-8") as f:
            json.dump(ground_truth, f, indent=2)

        return out_dir

    def _generate_test_sh(self, task: AINativeBenchTask) -> str:
        """
        Generate test.sh content for verification.

        Args:
            task: The AINativeBenchTask instance.

        Returns:
            Shell script content.
        """
        return f"""#!/bin/bash
# AINativeBench Verification Script
# Task: {task.id}
# Benchmark: {task.benchmark_name}
# Variant: {task.variant}

set -uo pipefail

echo "=== AINativeBench Verifier ==="
echo "Task ID: {task.id}"
echo "Benchmark: {task.benchmark_name}"
echo "Variant: {task.variant}"

# Create output directories
mkdir -p /logs/verifier

# Check for test_results directory (AINativeBench native output format)
TEST_RESULTS_DIR="/test_results"
if [ ! -d "$TEST_RESULTS_DIR" ]; then
    # Check alternative locations
    if [ -d "/app/test_results" ]; then
        TEST_RESULTS_DIR="/app/test_results"
    elif [ -d "/workspace/test_results" ]; then
        TEST_RESULTS_DIR="/workspace/test_results"
    fi
fi

# Check for ground truth
if [ ! -f /tests/ground_truth.json ]; then
    echo "ERROR: ground_truth.json not found"
    echo '{{"score": 0.0, "error": "Missing ground truth"}}' > /logs/verifier/reward.json
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

echo "Looking for test results in: $TEST_RESULTS_DIR"

# Run Python verifier to parse test_results and generate reward.json
python3 /tests/verify.py \\
    --test-results-dir "$TEST_RESULTS_DIR" \\
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

    def _generate_verify_py(self) -> str:
        """
        Generate verify.py content for parsing test_results/ JSON to reward.json.

        Returns:
            Python script content.
        """
        return '''#!/usr/bin/env python3
"""
AINativeBench Verifier

Parses AINativeBench's native test_results/ JSON output and converts
it to Harbor's reward.json format.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def parse_test_results(test_results_dir: Path) -> dict[str, Any]:
    """
    Parse test results from AINativeBench's native output format.

    AINativeBench stores test results as JSON files in test_results/ directory.

    Args:
        test_results_dir: Path to test_results directory.

    Returns:
        Aggregated test results.
    """
    results = {
        "total_tests": 0,
        "passed_tests": 0,
        "failed_tests": 0,
        "test_details": [],
    }

    if not test_results_dir.exists():
        return results

    # Find all JSON result files
    json_files = list(test_results_dir.glob("*.json"))

    for json_file in json_files:
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                test_result = json.load(f)

            results["total_tests"] += 1

            # Check for pass/fail status
            # AINativeBench uses various status indicators
            passed = False
            if isinstance(test_result, dict):
                # Check common status fields
                if test_result.get("passed", False):
                    passed = True
                elif test_result.get("status") == "passed":
                    passed = True
                elif test_result.get("result") == "pass":
                    passed = True
                elif test_result.get("success", False):
                    passed = True

            if passed:
                results["passed_tests"] += 1
            else:
                results["failed_tests"] += 1

            results["test_details"].append({
                "file": json_file.name,
                "passed": passed,
                "data": test_result,
            })

        except (json.JSONDecodeError, IOError) as e:
            results["test_details"].append({
                "file": json_file.name,
                "passed": False,
                "error": str(e),
            })
            results["total_tests"] += 1
            results["failed_tests"] += 1

    return results


def compute_score(
    test_results: dict[str, Any],
    ground_truth: dict[str, Any],
) -> dict[str, Any]:
    """
    Compute the final score based on test results and ground truth.

    Args:
        test_results: Parsed test results.
        ground_truth: Ground truth data including scoring metrics.

    Returns:
        Score dictionary in Harbor reward.json format.
    """
    total = test_results["total_tests"]
    passed = test_results["passed_tests"]

    # Compute pass rate
    if total > 0:
        pass_rate = passed / total
    else:
        pass_rate = 0.0

    # Get scoring metrics from ground truth
    scoring_metrics = ground_truth.get("scoring_metrics", {})
    primary_metric = scoring_metrics.get("primary_metric", "pass_rate")

    # Build reward result
    result = {
        "score": round(pass_rate, 4),
        "metrics": {
            "pass_rate": round(pass_rate, 4),
            "total_tests": total,
            "passed_tests": passed,
            "failed_tests": test_results["failed_tests"],
        },
        "primary_metric": primary_metric,
        "test_details": test_results["test_details"],
    }

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="AINativeBench Verifier")
    parser.add_argument(
        "--test-results-dir",
        required=True,
        help="Path to test_results directory",
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

    test_results_dir = Path(args.test_results_dir)
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

    # Parse test results
    test_results = parse_test_results(test_results_dir)

    if test_results["total_tests"] == 0:
        # No test results found - check if this is expected
        print("Warning: No test results found in test_results directory")
        result = {
            "score": 0.0,
            "metrics": {
                "pass_rate": 0.0,
                "total_tests": 0,
                "passed_tests": 0,
                "failed_tests": 0,
            },
            "error": "No test results found",
        }
    else:
        # Compute score
        result = compute_score(test_results, ground_truth)

    # Write output
    output_path.write_text(json.dumps(result, indent=2))

    print(f"Evaluation complete:")
    print(f"  Score: {result['score']}")
    if "metrics" in result:
        print(f"  Pass rate: {result['metrics'].get('pass_rate', 'N/A')}")
        print(f"  Tests: {result['metrics'].get('passed_tests', 0)}/{result['metrics'].get('total_tests', 0)}")


if __name__ == "__main__":
    main()
'''
