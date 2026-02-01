"""
LoCoBench-Agent Adapter for Harbor

Converts LoCoBench-Agent scenarios into Harbor task structure for benchmark execution.
"""

import json
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Union

# Import Harbor models from installed package
from harbor.models.task.config import TaskConfig
from harbor.models.task.paths import TaskPaths

ADAPTER_NAME = "locobench-agent"
TEMPLATE_DIR = Path(__file__).parent / "templates"


@dataclass
class LoCoBenchTask:
    """Represents a single LoCoBench-Agent task scenario.

    Fields match the normalized JSONL output from extract_dataset.py plus
    additional fields from the raw scenario for complete task context.
    """

    id: str
    task_category: str
    difficulty: str
    title: str
    description: str
    context_files: List[str]
    context_length: int
    task_prompt: str
    ground_truth: Union[str, Dict[str, Any]]
    evaluation_criteria: List[str]
    language: str
    expected_approach: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LoCoBenchTask":
        """Create a LoCoBenchTask from a dictionary.

        Args:
            data: Dictionary containing task fields. Can be from either
                  the normalized JSONL or raw scenario JSON.

        Returns:
            LoCoBenchTask instance.
        """
        # Parse language from id if not provided
        language = data.get("language", "")
        if not language and data.get("id"):
            parts = data["id"].split("_")
            language = parts[0] if parts else "unknown"

        return cls(
            id=data.get("id", ""),
            task_category=data.get("task_category", ""),
            difficulty=data.get("difficulty", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            context_files=data.get("context_files", []),
            context_length=data.get("context_length", 0),
            task_prompt=data.get("task_prompt", ""),
            ground_truth=data.get("ground_truth", ""),
            evaluation_criteria=data.get("evaluation_criteria", []),
            language=language,
            expected_approach=data.get("expected_approach", ""),
        )


class LoCoBenchLoader:
    """Loads LoCoBench-Agent tasks from dataset files.

    Supports loading from either:
    - Normalized JSONL files (from extract_dataset.py)
    - Raw scenario JSON files (from data/output/scenarios/)

    When loading from JSONL, supplements missing fields (context_files,
    description, expected_approach) from raw scenario files if available.
    """

    def __init__(
        self,
        dataset_path: Optional[Path] = None,
        data_dir: Optional[Path] = None,
    ):
        """Initialize the loader.

        Args:
            dataset_path: Path to JSONL dataset file. If None, tasks must be
                          loaded individually from raw JSON files.
            data_dir: Directory containing raw scenario files (data/output/scenarios/).
                      If None, defaults to benchmarks/locobench_agent/data/
        """
        self.dataset_path = dataset_path
        self.data_dir = Path(data_dir) if data_dir else Path(__file__).parent / "data"
        self._tasks: Dict[str, LoCoBenchTask] = {}
        self._raw_data_cache: Dict[str, Dict[str, Any]] = {}

        if dataset_path and dataset_path.exists():
            self._load_dataset()

    def _get_raw_scenario_path(self, task_id: str) -> Path:
        """Get path to raw scenario JSON file."""
        return self.data_dir / "output" / "scenarios" / f"{task_id}.json"

    def _load_raw_scenario(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Load raw scenario data for supplementing JSONL fields."""
        if task_id in self._raw_data_cache:
            return self._raw_data_cache[task_id]

        raw_path = self._get_raw_scenario_path(task_id)
        if raw_path.exists():
            with open(raw_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self._raw_data_cache[task_id] = data
                return data
        return None

    def _load_dataset(self) -> None:
        """Load tasks from JSONL dataset file."""
        if not self.dataset_path:
            return

        with open(self.dataset_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)

                # Supplement missing fields from raw scenario if available
                task_id = data.get("id", "")
                if task_id:
                    raw_data = self._load_raw_scenario(task_id)
                    if raw_data:
                        # Only add fields that are missing from JSONL
                        for field in ["context_files", "description", "expected_approach"]:
                            if field not in data or not data[field]:
                                if field in raw_data:
                                    data[field] = raw_data[field]

                task = LoCoBenchTask.from_dict(data)
                self._tasks[task.id] = task

    def load(self, task_id: str) -> LoCoBenchTask:
        """Load a single task by ID.

        Args:
            task_id: The task/scenario ID.

        Returns:
            LoCoBenchTask instance.

        Raises:
            KeyError: If task is not found.
        """
        if task_id in self._tasks:
            return self._tasks[task_id]
        raise KeyError(f"Task not found: {task_id}")

    def all_ids(self) -> List[str]:
        """Return all task IDs.

        Returns:
            Sorted list of all loaded task IDs.
        """
        return sorted(self._tasks.keys())

    def filter_by_task_category(self, category: str) -> List[LoCoBenchTask]:
        """Filter tasks by task category.

        Args:
            category: Task category to filter by (e.g., 'architectural_understanding').

        Returns:
            List of tasks matching the category.
        """
        return [
            task for task in self._tasks.values()
            if task.task_category == category
        ]

    def filter_by_language(self, language: str) -> List[LoCoBenchTask]:
        """Filter tasks by programming language.

        Args:
            language: Programming language to filter by (e.g., 'python', 'rust').

        Returns:
            List of tasks matching the language.
        """
        return [
            task for task in self._tasks.values()
            if task.language == language
        ]

    def filter_by_difficulty(self, difficulty: str) -> List[LoCoBenchTask]:
        """Filter tasks by difficulty level.

        Args:
            difficulty: Difficulty level to filter by (e.g., 'expert', 'hard').

        Returns:
            List of tasks matching the difficulty.
        """
        return [
            task for task in self._tasks.values()
            if task.difficulty == difficulty
        ]

    def get_all_tasks(self) -> List[LoCoBenchTask]:
        """Return all loaded tasks.

        Returns:
            List of all LoCoBenchTask instances.
        """
        return list(self._tasks.values())


class RequireNameMeta(type(ABC)):
    """Metaclass that requires subclasses to define a NAME attribute."""

    def __init__(cls, name, bases, dct):
        type.__init__(cls, name, bases, dct)
        if name != "BaseAdapter" and not hasattr(cls, "NAME"):
            raise TypeError(f"Class {name} must define a class property 'NAME'.")


class BaseAdapter(ABC, metaclass=RequireNameMeta):
    """Abstract base class for benchmark adapters."""

    NAME: ClassVar[str]

    def __init__(self, **kwargs):
        super().__init__()

    @abstractmethod
    def generate_task(
        self,
        task_id: str,
        local_task_id: str,
    ) -> None:
        raise NotImplementedError("Adapter must implement this method.")


class LoCoBenchAdapter(BaseAdapter):
    """Adapter that converts LoCoBench-Agent tasks into Harbor task directories."""

    NAME = "locobench-agent"

    def __init__(
        self,
        task_dir: Path,
        data_dir: Optional[Path] = None,
        dataset_path: Optional[Path] = None,
        **kwargs
    ):
        """
        Initialize LoCoBench-Agent adapter.

        Args:
            task_dir: Output directory for Harbor tasks
            data_dir: Directory containing LoCoBench data (generated/ and output/).
                      Defaults to benchmarks/locobench_agent/data/
            dataset_path: Path to JSONL dataset file
            **kwargs: Additional arguments
        """
        super().__init__(**kwargs)
        self.task_dir = Path(task_dir)
        self.data_dir = Path(data_dir) if data_dir else Path(__file__).parent / "data"
        self.loader = LoCoBenchLoader(dataset_path)
        self.templates_dir = TEMPLATE_DIR

    def _get_project_dir(self, task: LoCoBenchTask) -> Path:
        """
        Get the path to the synthetic project directory for a task.

        The project directory is derived from the scenario ID:
        - Scenario ID: python_api_gateway_expert_045_bug_investigation_hard_01
        - Project prefix: python_api_gateway_expert_045
        - Path: data/generated/python_api_gateway_expert_045/

        Args:
            task: The LoCoBenchTask instance

        Returns:
            Path to the project directory
        """
        # Extract project prefix from task ID
        # Format: {lang}_{domain}_{complexity}_{num}_{category}_{difficulty}_{variant}
        parts = task.id.split("_")
        if len(parts) >= 4:
            # Find where the task_category starts by looking for known categories
            categories = {
                "architectural", "bug", "code", "cross",
                "feature", "integration", "multi", "security"
            }
            project_parts = []
            for i, part in enumerate(parts):
                if part.lower() in categories:
                    break
                project_parts.append(part)
            project_prefix = "_".join(project_parts)
        else:
            project_prefix = task.id

        return self.data_dir / "generated" / project_prefix

    def _render_template(self, template_path: Path, context: Dict[str, Any]) -> str:
        """
        Simple template rendering by replacing {key} placeholders.

        Args:
            template_path: Path to the template file
            context: Dictionary of placeholder values

        Returns:
            Rendered template string
        """
        content = template_path.read_text()
        for key, value in context.items():
            # Handle both {key} and {{ key }} formats
            content = content.replace(f"{{{key}}}", str(value))
            content = content.replace(f"{{{{ {key} }}}}", str(value))
        return content

    def _generate_dockerfile(self, language: str) -> str:
        """
        Generate a language-specific Dockerfile.

        Each task only needs its own language toolchain, not all 10 languages.
        This significantly reduces build time.

        Args:
            language: Programming language (e.g., 'python', 'rust', 'go')

        Returns:
            Dockerfile content as string
        """
        # Base image and common setup
        base = """FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install base dependencies
RUN apt-get update && apt-get install -y \\
    build-essential \\
    curl \\
    wget \\
    git \\
    ca-certificates \\
    jq \\
    && rm -rf /var/lib/apt/lists/*

"""
        # Language-specific installations
        lang_installs = {
            "python": """# Install Python 3.10
RUN apt-get update && apt-get install -y \\
    python3.10 \\
    python3.10-dev \\
    python3-pip \\
    && rm -rf /var/lib/apt/lists/*
""",
            "javascript": """# Install Node.js 20
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \\
    && apt-get install -y nodejs \\
    && rm -rf /var/lib/apt/lists/*
""",
            "typescript": """# Install Node.js 20 (for TypeScript)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \\
    && apt-get install -y nodejs \\
    && rm -rf /var/lib/apt/lists/*
""",
            "rust": """# Install Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"
""",
            "go": """# Install Go
RUN wget https://go.dev/dl/go1.21.0.linux-amd64.tar.gz \\
    && tar -C /usr/local -xzf go1.21.0.linux-amd64.tar.gz \\
    && rm go1.21.0.linux-amd64.tar.gz
ENV PATH="/usr/local/go/bin:${PATH}"
""",
            "java": """# Install Java 17
RUN apt-get update && apt-get install -y openjdk-17-jdk \\
    && rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
""",
            "csharp": """# Install .NET 7
RUN wget https://packages.microsoft.com/config/ubuntu/22.04/packages-microsoft-prod.deb -O packages-microsoft-prod.deb \\
    && dpkg -i packages-microsoft-prod.deb \\
    && rm packages-microsoft-prod.deb \\
    && apt-get update && apt-get install -y dotnet-sdk-7.0 \\
    && rm -rf /var/lib/apt/lists/*
""",
            "php": """# Install PHP
RUN apt-get update && apt-get install -y php php-cli php-mbstring \\
    && rm -rf /var/lib/apt/lists/*
""",
            "c": """# C uses build-essential (already installed)
""",
            "cpp": """# C++ uses build-essential (already installed)
RUN apt-get update && apt-get install -y g++ \\
    && rm -rf /var/lib/apt/lists/*
""",
        }

        # Get language install (default to Python for verifier compatibility)
        lang_install = lang_installs.get(language.lower(), lang_installs["python"])

        # Always include Python for the verifier
        if language.lower() not in ("python",):
            lang_install += """
# Install Python 3 for verifier
RUN apt-get update && apt-get install -y python3 python3-pip \\
    && rm -rf /var/lib/apt/lists/*
"""

        # Common footer
        footer = """
# Create working directories
RUN mkdir -p /app /logs /workspace /tests

# Copy project files
COPY project /app/project

WORKDIR /app

CMD ["/bin/bash"]
"""
        return base + lang_install + footer

    def _create_instruction(self, task: LoCoBenchTask) -> str:
        """
        Create instruction.md content for the task.

        Args:
            task: The LoCoBenchTask instance

        Returns:
            Rendered instruction content
        """
        template_path = self.templates_dir / "instruction.md"

        # Format evaluation criteria as markdown list
        if task.evaluation_criteria:
            criteria_text = "\n".join(f"- {c}" for c in task.evaluation_criteria)
        else:
            criteria_text = "- Complete the task accurately and thoroughly"

        # Get files count from context_files
        files_count = len(task.context_files) if task.context_files else 0

        # Use expected_approach from task, or provide a default
        expected_approach = task.expected_approach if task.expected_approach else (
            "Analyze the code systematically and provide a comprehensive solution."
        )

        context = {
            "id": task.id,
            "task_category": task.task_category,
            "difficulty": task.difficulty,
            "language": task.language,
            "context_length": task.context_length,
            "files_count": files_count,
            "title": task.title,
            "description": task.description,
            "task_prompt": task.task_prompt,
            "expected_approach": expected_approach,
            "evaluation_criteria": criteria_text,
        }

        return self._render_template(template_path, context)

    def _prepare_task_from_template(
        self,
        task: LoCoBenchTask,
        output_dir: Path,
    ) -> None:
        """
        Prepare a LoCoBench task directory in Harbor structure.

        Args:
            task: The LoCoBenchTask instance
            output_dir: Output directory for the task
        """
        # Clean and create output directory
        shutil.rmtree(output_dir, ignore_errors=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize TaskPaths for Harbor structure
        task_paths = TaskPaths(task_dir=output_dir)

        # Create directory structure
        task_paths.tests_dir.mkdir(parents=True, exist_ok=True)
        task_paths.environment_dir.mkdir(parents=True, exist_ok=True)

        # Get files count
        files_count = len(task.context_files) if task.context_files else 0

        # 1. Write instruction.md
        instruction = self._create_instruction(task)
        task_paths.instruction_path.write_text(instruction)

        # 2. Create task.toml
        task_toml_template = self.templates_dir / "task.toml"
        if task_toml_template.exists():
            template_content = task_toml_template.read_text()
            task_config = TaskConfig.model_validate_toml(template_content)

            # Update metadata with actual task values
            task_config.metadata["difficulty"] = task.difficulty
            task_config.metadata["category"] = task.task_category
            task_config.metadata["language"] = task.language
            task_config.metadata["context_length"] = task.context_length
            task_config.metadata["files_count"] = files_count
            task_config.metadata["task_id"] = task.id
            task_config.metadata["tags"] = [
                "locobench-agent",
                task.task_category,
                task.language,
            ]

            task_paths.config_path.write_text(task_config.model_dump_toml())
        else:
            raise FileNotFoundError(f"Template {task_toml_template} not found")

        # 3. Copy project files to environment/project
        project_dir = self._get_project_dir(task)
        env_project_dir = task_paths.environment_dir / "project"

        if project_dir.exists():
            # Find the actual project subdirectory (e.g., EduGate_ScholarLink)
            project_subdirs = [
                d for d in project_dir.iterdir()
                if d.is_dir() and d.name != "__pycache__"
            ]
            if project_subdirs:
                # Copy the project content
                actual_project = project_subdirs[0]
                shutil.copytree(actual_project, env_project_dir, symlinks=True)
            else:
                # No subdirectory found, copy the whole thing
                shutil.copytree(project_dir, env_project_dir, symlinks=True)
        else:
            # Create empty project directory
            env_project_dir.mkdir(parents=True, exist_ok=True)

        # 4. Generate language-specific Dockerfile
        dockerfile_content = self._generate_dockerfile(task.language)
        (task_paths.environment_dir / "Dockerfile").write_text(dockerfile_content)

        # 5. Save ground truth
        ground_truth_data = {
            "ground_truth": task.ground_truth,
            "context_files": [f.replace("//", "/") for f in task.context_files],
            "task_category": task.task_category,
            "evaluation_criteria": task.evaluation_criteria,
        }
        ground_truth_path = task_paths.tests_dir / "ground_truth.json"
        with open(ground_truth_path, "w") as f:
            json.dump(ground_truth_data, f, indent=2)

        # 6. Generate tests/test.sh
        test_template = self.templates_dir / "tests" / "test.sh"
        if test_template.exists():
            test_content = self._render_template(
                test_template,
                {
                    "id": task.id,
                    "task_category": task.task_category,
                }
            )
            task_paths.test_path.write_text(test_content)
            task_paths.test_path.chmod(0o755)
        else:
            raise FileNotFoundError(f"Template {test_template} not found")

        # 7. Copy verify.py to tests directory
        verify_template = self.templates_dir / "tests" / "verify.py"
        if verify_template.exists():
            verify_dest = task_paths.tests_dir / "verify.py"
            shutil.copy(verify_template, verify_dest)
            verify_dest.chmod(0o755)
        else:
            raise FileNotFoundError(f"Template {verify_template} not found")

        # 8. Save task metadata for debugging/reference
        metadata_path = task_paths.tests_dir / "task_metadata.json"
        with open(metadata_path, "w") as f:
            json.dump({
                "task_id": task.id,
                "task_category": task.task_category,
                "difficulty": task.difficulty,
                "language": task.language,
                "context_length": task.context_length,
                "files_count": files_count,
                "title": task.title,
            }, f, indent=2)

        # 9. Generate solution/solve.sh for oracle agent testing
        solution_dir = output_dir / "solution"
        solution_dir.mkdir(parents=True, exist_ok=True)

        solve_template = self.templates_dir / "solution" / "solve.sh"
        if solve_template.exists():
            # Format ground truth content for embedding in bash heredoc
            if isinstance(task.ground_truth, dict):
                ground_truth_content = json.dumps(task.ground_truth, indent=2)
            else:
                ground_truth_content = str(task.ground_truth)

            solve_content = self._render_template(
                solve_template,
                {"ground_truth_content": ground_truth_content}
            )
            solve_path = solution_dir / "solve.sh"
            solve_path.write_text(solve_content)
            solve_path.chmod(0o755)

    def generate_task(self, task_id: str, local_task_id: str) -> None:
        """
        Generate a new Harbor task for a LoCoBench-Agent scenario.

        Args:
            task_id: LoCoBench task/scenario ID
            local_task_id: Local directory name for the task
        """
        task = self.loader.load(task_id)
        out_dir = self.task_dir / local_task_id
        out_dir.mkdir(parents=True, exist_ok=True)

        self._prepare_task_from_template(task, out_dir)
