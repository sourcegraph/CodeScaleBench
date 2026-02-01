"""
PRDBench data model and loader.

PRDBench is a benchmark for evaluating LLM-powered coding agents on PRD-driven
development tasks. Each task contains:
- A Product Requirements Document (PRD) as the main instruction
- A detailed test plan with evaluation criteria
- Specific evaluation criteria for judging task completion

The loader reads tasks from the PRDBench directory structure:
    {task_id}/
    ├── src/
    │   └── PRD.md
    └── evaluation/
        └── detailed_test_plan.json

Each task is evaluated based on how well the agent implements the PRD.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json


@dataclass
class EvaluationCriterion:
    """
    A single evaluation criterion for a PRDBench task.

    Evaluation criteria define how to judge whether a requirement
    has been met. Each criterion has a weight contributing to
    the final score.

    Attributes:
        id: Unique criterion identifier (e.g., 'C1', 'C1.1')
        name: Human-readable criterion name
        description: Detailed description of what to evaluate
        weight: Weight of this criterion in the final score (0.0-1.0)
        category: Criterion category (functional, ui, performance, etc.)
        automated: Whether this can be evaluated automatically
    """

    id: str
    name: str
    description: str
    weight: float = 1.0
    category: str = "functional"
    automated: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "weight": self.weight,
            "category": self.category,
            "automated": self.automated,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationCriterion":
        """Create an EvaluationCriterion from a dictionary."""
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            weight=data.get("weight", 1.0),
            category=data.get("category", "functional"),
            automated=data.get("automated", False),
        )


@dataclass
class EvaluationPlan:
    """
    A test plan for evaluating a PRDBench task.

    The test plan contains structured evaluation criteria
    and test cases for validating PRD implementation.

    Attributes:
        version: Test plan version
        task_id: ID of the associated task
        criteria: List of evaluation criteria
        test_cases: List of test case descriptions
        scoring: Scoring configuration (weights, thresholds)
        metadata: Additional test plan metadata
    """

    version: str
    task_id: str
    criteria: list[EvaluationCriterion] = field(default_factory=list)
    test_cases: list[dict[str, Any]] = field(default_factory=list)
    scoring: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "version": self.version,
            "task_id": self.task_id,
            "criteria": [c.to_dict() for c in self.criteria],
            "test_cases": self.test_cases,
            "scoring": self.scoring,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvaluationPlan":
        """Create a EvaluationPlan from a dictionary."""
        # Parse criteria
        criteria_data = data.get("criteria", [])
        criteria = [
            EvaluationCriterion.from_dict(c) if isinstance(c, dict) else c
            for c in criteria_data
        ]

        return cls(
            version=data.get("version", "1.0"),
            task_id=data.get("task_id", ""),
            criteria=criteria,
            test_cases=data.get("test_cases", []),
            scoring=data.get("scoring", {}),
            metadata=data.get("metadata", {}),
        )

    def get_total_weight(self) -> float:
        """
        Get total weight of all criteria.

        Returns:
            Sum of all criterion weights.
        """
        return sum(c.weight for c in self.criteria)

    def get_criteria_by_category(self, category: str) -> list[EvaluationCriterion]:
        """
        Filter criteria by category.

        Args:
            category: Category to filter by.

        Returns:
            List of criteria matching the category.
        """
        return [c for c in self.criteria if c.category == category]

    def criterion_count(self) -> int:
        """
        Get number of evaluation criteria.

        Returns:
            Number of criteria in the test plan.
        """
        return len(self.criteria)


@dataclass
class PRDBenchTask:
    """
    Data model for a PRDBench task.

    Attributes:
        id: Unique task identifier (e.g., 'prdbench-001')
        prd_content: The Product Requirements Document content (markdown)
        test_plan: Structured test plan for evaluation
        evaluation_criteria: List of evaluation criteria (convenience accessor)
        title: Task title extracted from PRD
        description: Brief task description
        difficulty: Task difficulty (easy, medium, hard)
        metadata: Additional task metadata
    """

    id: str
    prd_content: str
    test_plan: EvaluationPlan | None = None
    evaluation_criteria: list[EvaluationCriterion] = field(default_factory=list)
    title: str = ""
    description: str = ""
    difficulty: str = "medium"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Initialize evaluation_criteria from test_plan if not provided."""
        # If we have a test_plan but no evaluation_criteria, populate from test_plan
        if self.test_plan and not self.evaluation_criteria:
            self.evaluation_criteria = list(self.test_plan.criteria)
        # If we have evaluation_criteria but no test_plan, create a basic test_plan
        elif self.evaluation_criteria and not self.test_plan:
            self.test_plan = EvaluationPlan(
                version="1.0",
                task_id=self.id,
                criteria=self.evaluation_criteria,
            )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "prd_content": self.prd_content,
            "test_plan": self.test_plan.to_dict() if self.test_plan else None,
            "evaluation_criteria": [c.to_dict() for c in self.evaluation_criteria],
            "title": self.title,
            "description": self.description,
            "difficulty": self.difficulty,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PRDBenchTask":
        """Create a PRDBenchTask from a dictionary."""
        # Parse test_plan
        test_plan_data = data.get("test_plan")
        test_plan = None
        if test_plan_data and isinstance(test_plan_data, dict):
            test_plan = EvaluationPlan.from_dict(test_plan_data)

        # Parse evaluation_criteria
        criteria_data = data.get("evaluation_criteria", [])
        evaluation_criteria = [
            EvaluationCriterion.from_dict(c) if isinstance(c, dict) else c
            for c in criteria_data
        ]

        return cls(
            id=data.get("id", ""),
            prd_content=data.get("prd_content", ""),
            test_plan=test_plan,
            evaluation_criteria=evaluation_criteria,
            title=data.get("title", ""),
            description=data.get("description", ""),
            difficulty=data.get("difficulty", "medium"),
            metadata=data.get("metadata", {}),
        )

    def get_criterion_count(self) -> int:
        """
        Get total number of evaluation criteria.

        Returns:
            Number of evaluation criteria.
        """
        return len(self.evaluation_criteria)

    def get_prd_sections(self) -> list[str]:
        """
        Extract section headers from the PRD content.

        Returns:
            List of section headers found in the PRD.
        """
        sections = []
        for line in self.prd_content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("#"):
                # Remove '#' characters and whitespace
                section = stripped.lstrip("#").strip()
                if section:
                    sections.append(section)
        return sections

    def extract_title_from_prd(self) -> str:
        """
        Extract title from the first heading in the PRD.

        Returns:
            Title extracted from PRD, or empty string if not found.
        """
        for line in self.prd_content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
        return ""


class PRDBenchLoader:
    """
    Loader for PRDBench tasks.

    Reads tasks from the PRDBench dataset structure. Supports loading from
    individual task directories or a manifest/combined file.

    Expected directory structure (individual directories):
        data_dir/
        ├── task-001/
        │   ├── src/
        │   │   └── PRD.md
        │   └── evaluation/
        │       └── detailed_test_plan.json
        ├── task-002/
        │   ├── src/
        │   │   └── PRD.md
        │   └── evaluation/
        │       └── detailed_test_plan.json
        └── ...

    Alternative structure (manifest):
        data_dir/
        ├── manifest.json
        └── tasks/
            └── ...

    Alternative structure (combined):
        data_dir/
        └── tasks.json  (array of all tasks)
    """

    def __init__(self, data_dir: str | Path | None = None) -> None:
        """
        Initialize the loader.

        Args:
            data_dir: Path to the PRDBench data directory.
                      If None, uses default path relative to this module.
        """
        if data_dir is None:
            # Default to a data directory relative to this module
            self.data_dir = Path(__file__).parent / "data"
        else:
            self.data_dir = Path(data_dir)

        self._tasks: list[PRDBenchTask] = []
        self._loaded = False

    def load(self) -> list[PRDBenchTask]:
        """
        Load all tasks from the data directory.

        Attempts to load from:
        1. tasks.json (combined file)
        2. manifest.json (manifest-based loading)
        3. Individual task directories with {task_id}/src/PRD.md structure

        Returns:
            List of all PRDBenchTask objects.
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
        # Load from individual task directories
        elif self.data_dir.exists():
            self._load_from_directories()

        self._loaded = True
        return self._tasks

    def _load_from_combined_file(self, tasks_file: Path) -> None:
        """Load tasks from a single combined JSON file."""
        try:
            with open(tasks_file, encoding="utf-8") as f:
                data = json.load(f)

            # Handle both array of tasks and object with 'tasks' key
            if isinstance(data, list):
                tasks_data = data
            elif isinstance(data, dict):
                tasks_data = data.get("tasks", [])
            else:
                return

            for task_data in tasks_data:
                try:
                    task = PRDBenchTask.from_dict(task_data)
                    self._tasks.append(task)
                except (KeyError, TypeError) as e:
                    print(f"Warning: Failed to parse task: {e}")

        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to load tasks.json: {e}")

    def _load_from_manifest(self, manifest_path: Path) -> None:
        """Load tasks from a manifest file."""
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)

            tasks_list = manifest.get("tasks", [])

            for task_entry in tasks_list:
                # Handle both string (task_id) and dict (full task data)
                if isinstance(task_entry, str):
                    task = self._load_task_directory(self.data_dir / task_entry)
                elif isinstance(task_entry, dict):
                    task_id = task_entry.get("id", task_entry.get("task_id"))
                    if task_id:
                        task = self._load_task_directory(self.data_dir / task_id)
                    else:
                        continue
                else:
                    continue

                if task:
                    self._tasks.append(task)

        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to load manifest: {e}")

    def _load_from_directories(self) -> None:
        """Load tasks from individual task directories."""
        # Look for directories containing src/PRD.md
        for item in self.data_dir.iterdir():
            if item.is_dir():
                prd_path = item / "src" / "PRD.md"
                if prd_path.exists():
                    task = self._load_task_directory(item)
                    if task:
                        self._tasks.append(task)

    def _load_task_directory(self, task_dir: Path) -> PRDBenchTask | None:
        """
        Load a single task from a directory.

        Expected structure:
            task_dir/
            ├── src/
            │   └── PRD.md
            └── evaluation/
                └── detailed_test_plan.json

        Args:
            task_dir: Path to the task directory.

        Returns:
            PRDBenchTask if successful, None otherwise.
        """
        task_id = task_dir.name
        prd_path = task_dir / "src" / "PRD.md"
        test_plan_path = task_dir / "evaluation" / "detailed_test_plan.json"

        # Read PRD content (required)
        if not prd_path.exists():
            print(f"Warning: PRD.md not found in {task_dir}")
            return None

        try:
            prd_content = prd_path.read_text(encoding="utf-8")
        except IOError as e:
            print(f"Warning: Failed to read PRD.md from {task_dir}: {e}")
            return None

        # Read test plan (optional)
        test_plan = None
        evaluation_criteria: list[EvaluationCriterion] = []

        if test_plan_path.exists():
            try:
                with open(test_plan_path, encoding="utf-8") as f:
                    test_plan_data = json.load(f)

                # Set task_id in test plan data
                test_plan_data["task_id"] = task_id
                test_plan = EvaluationPlan.from_dict(test_plan_data)
                evaluation_criteria = list(test_plan.criteria)

            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Failed to load test plan from {task_dir}: {e}")

        # Extract title from PRD
        title = ""
        for line in prd_content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("# "):
                title = stripped[2:].strip()
                break

        # Check for additional metadata
        metadata_path = task_dir / "metadata.json"
        metadata: dict[str, Any] = {}
        if metadata_path.exists():
            try:
                with open(metadata_path, encoding="utf-8") as f:
                    metadata = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass

        return PRDBenchTask(
            id=task_id,
            prd_content=prd_content,
            test_plan=test_plan,
            evaluation_criteria=evaluation_criteria,
            title=title,
            difficulty=metadata.get("difficulty", "medium"),
            metadata=metadata,
        )

    def all_ids(self) -> list[str]:
        """
        Get all task IDs.

        Returns:
            List of all task IDs in the loaded dataset.
        """
        if not self._loaded:
            self.load()
        return [task.id for task in self._tasks]

    def get_task(self, task_id: str) -> PRDBenchTask | None:
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

    def filter_by_difficulty(self, difficulty: str) -> list[PRDBenchTask]:
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

    def filter_by_criteria_count(
        self,
        min_criteria: int | None = None,
        max_criteria: int | None = None,
    ) -> list[PRDBenchTask]:
        """
        Filter tasks by number of evaluation criteria.

        Args:
            min_criteria: Minimum number of criteria (inclusive).
            max_criteria: Maximum number of criteria (inclusive).

        Returns:
            List of tasks matching the criteria count range.
        """
        if not self._loaded:
            self.load()

        result = []
        for task in self._tasks:
            count = task.get_criterion_count()
            if min_criteria is not None and count < min_criteria:
                continue
            if max_criteria is not None and count > max_criteria:
                continue
            result.append(task)

        return result

    def total_criteria_count(self) -> int:
        """
        Get total number of evaluation criteria across all tasks.

        Returns:
            Total count of evaluation criteria.
        """
        if not self._loaded:
            self.load()
        return sum(task.get_criterion_count() for task in self._tasks)


# Template directory for Harbor task generation
TEMPLATE_DIR = Path(__file__).parent / "templates"


class PRDBenchAdapter:
    """
    Adapter that converts PRDBench tasks into Harbor task directories.

    Generates Harbor-compatible task structure with:
    - task.toml: Task configuration and metadata
    - instruction.md: Task instructions with embedded PRD content
    - environment/Dockerfile: Conda environment with multi-port support
    - tests/test.sh: Verification script
    - tests/verify.py: Validates test results against evaluation criteria
    - tests/ground_truth.json: Evaluation criteria and test plan

    PRDBench tasks use PRD.md documents as the primary instruction source,
    with structured test plans for evaluation.
    """

    NAME = "prdbench"

    def __init__(
        self,
        task_dir: str | Path,
        data_dir: str | Path | None = None,
    ) -> None:
        """
        Initialize the PRDBench adapter.

        Args:
            task_dir: Output directory for generated Harbor tasks.
            data_dir: Path to PRDBench data directory (optional).
        """
        self.task_dir = Path(task_dir)
        self.loader = PRDBenchLoader(data_dir)
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

    def _generate_dockerfile(self) -> str:
        """
        Generate Dockerfile for PRDBench tasks.

        Uses conda environment with multi-port configuration as specified.
        PRDBench tasks may require complex environments with multiple services.

        Returns:
            Dockerfile content as string.
        """
        return """FROM continuumio/miniconda3:latest

# Install system dependencies
RUN apt-get update && apt-get install -y \\
    build-essential \\
    curl \\
    git \\
    jq \\
    nginx \\
    supervisor \\
    nodejs \\
    npm \\
    && rm -rf /var/lib/apt/lists/*

# Create conda environment with common dependencies
RUN conda create -n prdbench python=3.11 -y && \\
    conda clean -afy

# Activate conda environment by default
SHELL ["/bin/bash", "-c"]
ENV PATH /opt/conda/envs/prdbench/bin:$PATH

# Install common Python packages in conda environment
RUN /opt/conda/envs/prdbench/bin/pip install --no-cache-dir \\
    flask \\
    fastapi \\
    uvicorn \\
    django \\
    pytest \\
    requests \\
    sqlalchemy \\
    redis \\
    celery \\
    pydantic

# Create working directories
RUN mkdir -p /app /logs /workspace /tests /config

# Multi-port configuration for services
# Default ports: 3000 (frontend), 5000 (backend API), 8000 (main app), 6379 (redis)
EXPOSE 3000 5000 8000 6379

# Supervisor configuration for multi-service management
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf 2>/dev/null || true

# Set up workspace
WORKDIR /workspace

# Copy project files
COPY project /workspace/project 2>/dev/null || true

# Entry point that activates conda environment
RUN echo '#!/bin/bash' > /entrypoint.sh && \\
    echo 'source /opt/conda/etc/profile.d/conda.sh' >> /entrypoint.sh && \\
    echo 'conda activate prdbench' >> /entrypoint.sh && \\
    echo 'exec "$@"' >> /entrypoint.sh && \\
    chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["/bin/bash"]
"""

    def _format_criteria_markdown(
        self, criteria: list[EvaluationCriterion]
    ) -> str:
        """
        Format evaluation criteria as markdown list.

        Args:
            criteria: List of EvaluationCriterion objects.

        Returns:
            Formatted markdown string.
        """
        if not criteria:
            return ""

        lines = ["### Evaluation Criteria\n"]

        # Group by category
        categories: dict[str, list[EvaluationCriterion]] = {}
        for crit in criteria:
            cat = crit.category
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(crit)

        for category, cat_criteria in categories.items():
            lines.append(f"\n#### {category.title()}\n")
            for crit in cat_criteria:
                # Weight indicator
                weight_str = f"(weight: {crit.weight:.1f})" if crit.weight != 1.0 else ""

                # Automated indicator
                auto_str = " ✓ Automated" if crit.automated else ""

                line = f"- **{crit.id}**: {crit.name} {weight_str}{auto_str}"
                if crit.description:
                    line += f"\n  - {crit.description}"
                lines.append(line)

        return "\n".join(lines)

    def _create_instruction(self, task: PRDBenchTask) -> str:
        """
        Create instruction.md content with embedded PRD.

        Args:
            task: The PRDBenchTask instance.

        Returns:
            Rendered instruction content.
        """
        template_path = self.templates_dir / "instruction.md"

        # Format criteria as markdown
        criteria_text = self._format_criteria_markdown(task.evaluation_criteria)

        # Extract title from PRD if not set
        title = task.title or task.extract_title_from_prd() or task.id

        context = {
            "id": task.id,
            "title": title,
            "difficulty": task.difficulty,
            "prd_content": task.prd_content,
            "criteria": criteria_text,
            "criteria_count": task.get_criterion_count(),
        }

        return self._render_template(template_path, context)

    def _create_task_toml(self, task: PRDBenchTask) -> str:
        """
        Create task.toml content for the task.

        Args:
            task: The PRDBenchTask instance.

        Returns:
            Task configuration as TOML string.
        """
        template_path = self.templates_dir / "task.toml"

        # Format tags
        tags = [
            "prdbench",
            task.difficulty,
        ]
        # Add criteria categories as tags
        if task.evaluation_criteria:
            categories = set(c.category for c in task.evaluation_criteria)
            tags.extend(categories)
        tags_str = ", ".join(f'"{t}"' for t in tags)

        # Extract title
        title = task.title or task.extract_title_from_prd() or task.id

        context = {
            "task_id": task.id,
            "title": title,
            "difficulty": task.difficulty,
            "criteria_count": task.get_criterion_count(),
            "tags": tags_str,
        }

        return self._render_template(template_path, context)

    def _create_ground_truth(self, task: PRDBenchTask) -> dict[str, Any]:
        """
        Create ground truth JSON for verification.

        Args:
            task: The PRDBenchTask instance.

        Returns:
            Ground truth dictionary.
        """
        return {
            "task_id": task.id,
            "title": task.title or task.extract_title_from_prd(),
            "difficulty": task.difficulty,
            "evaluation_criteria": [c.to_dict() for c in task.evaluation_criteria],
            "test_plan": task.test_plan.to_dict() if task.test_plan else None,
            "prd_sections": task.get_prd_sections(),
            "metadata": task.metadata,
        }

    def generate_task(self, task_id: str, local_task_id: str | None = None) -> Path:
        """
        Generate a Harbor task directory for a PRDBench task.

        Args:
            task_id: PRDBench task ID.
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

        # 5. Copy/generate test.sh template
        test_sh_template = self.templates_dir / "test.sh"
        if test_sh_template.exists():
            test_sh_content = self._render_template(
                test_sh_template,
                {"id": task.id, "title": task.title or task.id},
            )
        else:
            test_sh_content = self._generate_test_sh(task)
        test_sh_path = tests_dir / "test.sh"
        test_sh_path.write_text(test_sh_content)
        test_sh_path.chmod(0o755)

        # 6. Copy/generate verify.py template
        verify_py_template = self.templates_dir / "verify.py"
        if verify_py_template.exists():
            verify_py_content = verify_py_template.read_text()
        else:
            verify_py_content = self._generate_verify_py()
        verify_py_path = tests_dir / "verify.py"
        verify_py_path.write_text(verify_py_content)
        verify_py_path.chmod(0o755)

        # 7. Write ground truth with evaluation criteria
        ground_truth = self._create_ground_truth(task)
        ground_truth_path = tests_dir / "ground_truth.json"
        with open(ground_truth_path, "w", encoding="utf-8") as f:
            json.dump(ground_truth, f, indent=2)

        # 8. Write test plan if available
        if task.test_plan:
            test_plan_path = tests_dir / "test_plan.json"
            with open(test_plan_path, "w", encoding="utf-8") as f:
                json.dump(task.test_plan.to_dict(), f, indent=2)

        return out_dir

    def _generate_test_sh(self, task: PRDBenchTask) -> str:
        """
        Generate test.sh content for verification.

        Args:
            task: The PRDBenchTask instance.

        Returns:
            Shell script content.
        """
        title = task.title or task.extract_title_from_prd() or task.id
        return f"""#!/bin/bash
# PRDBench Verification Script
# Task: {task.id}
# Title: {title}

set -uo pipefail

echo "=== PRDBench Verifier ==="
echo "Task ID: {task.id}"
echo "Difficulty: {task.difficulty}"
echo "Evaluation Criteria: {task.get_criterion_count()}"

# Create output directories
mkdir -p /logs/verifier

# Activate conda environment if available
if [ -f /opt/conda/etc/profile.d/conda.sh ]; then
    source /opt/conda/etc/profile.d/conda.sh
    conda activate prdbench 2>/dev/null || true
fi

# Check for ground truth
if [ ! -f /tests/ground_truth.json ]; then
    echo "ERROR: ground_truth.json not found"
    echo '{{"score": 0.0, "error": "Missing ground truth"}}' > /logs/verifier/reward.json
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

# Look for test results in common locations
TEST_RESULTS=""
for path in /workspace/test_results.json /workspace/project/test_results.json /logs/test_results.json /app/test_results.json; do
    if [ -f "$path" ]; then
        TEST_RESULTS="$path"
        break
    fi
done

echo "Test results file: $TEST_RESULTS"

# Run Python verifier to evaluate against criteria
python3 /tests/verify.py \\
    --test-results "$TEST_RESULTS" \\
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
        Generate verify.py content for evaluating against criteria.

        Returns:
            Python script content.
        """
        return '''#!/usr/bin/env python3
"""
PRDBench Verifier

Evaluates agent output against evaluation criteria from the test plan.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def evaluate_criteria(
    test_results: dict[str, Any] | None,
    ground_truth: dict[str, Any],
) -> dict[str, Any]:
    """
    Evaluate test results against evaluation criteria.

    Args:
        test_results: Test results from the agent (may be None if no results).
        ground_truth: Ground truth with evaluation criteria.

    Returns:
        Evaluation result dictionary.
    """
    criteria = ground_truth.get("evaluation_criteria", [])
    total_criteria = len(criteria)

    if total_criteria == 0:
        return {
            "score": 0.0,
            "metrics": {
                "total_criteria": 0,
                "passed_criteria": 0,
            },
            "note": "No evaluation criteria defined",
        }

    if test_results is None:
        return {
            "score": 0.0,
            "metrics": {
                "total_criteria": total_criteria,
                "passed_criteria": 0,
                "criteria_results": {},
            },
            "note": "No test results provided",
        }

    # Extract criterion results from test results
    criterion_results = test_results.get("criteria_results", {})

    # Alternative: check for test pass/fail counts
    tests_passed = test_results.get("tests_passed", 0)
    tests_total = test_results.get("tests_total", 0)

    # Calculate score based on criteria
    passed_count = 0
    total_weight = 0.0
    weighted_score = 0.0
    criteria_scores: dict[str, dict[str, Any]] = {}

    for crit in criteria:
        crit_id = crit.get("id", "")
        crit_weight = crit.get("weight", 1.0)
        total_weight += crit_weight

        # Check if criterion passed
        passed = False
        if crit_id in criterion_results:
            result = criterion_results[crit_id]
            if isinstance(result, bool):
                passed = result
            elif isinstance(result, dict):
                passed = result.get("passed", False)

        if passed:
            passed_count += 1
            weighted_score += crit_weight

        criteria_scores[crit_id] = {
            "name": crit.get("name", ""),
            "passed": passed,
            "weight": crit_weight,
        }

    # Compute final score
    if total_weight > 0:
        score = weighted_score / total_weight
    elif total_criteria > 0:
        score = passed_count / total_criteria
    else:
        score = 0.0

    return {
        "score": round(score, 4),
        "metrics": {
            "total_criteria": total_criteria,
            "passed_criteria": passed_count,
            "total_weight": total_weight,
            "weighted_score": weighted_score,
            "criteria_scores": criteria_scores,
            "tests_passed": tests_passed,
            "tests_total": tests_total,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="PRDBench Verifier")
    parser.add_argument(
        "--test-results",
        help="Path to test results JSON file (optional)",
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

    # Read test results if provided
    test_results = None
    if args.test_results and args.test_results != "":
        test_results_path = Path(args.test_results)
        if test_results_path.exists():
            try:
                with open(test_results_path, "r", encoding="utf-8") as f:
                    test_results = json.load(f)
            except json.JSONDecodeError as e:
                print(f"Warning: Failed to parse test results: {e}")

    # Evaluate
    result = evaluate_criteria(test_results, ground_truth)

    # Write output
    output_path.write_text(json.dumps(result, indent=2))

    print(f"Evaluation complete:")
    print(f"  Score: {result.get('score', 0.0)}")
    metrics = result.get("metrics", {})
    print(f"  Criteria: {metrics.get('passed_criteria', 0)}/{metrics.get('total_criteria', 0)}")


if __name__ == "__main__":
    main()
'''
