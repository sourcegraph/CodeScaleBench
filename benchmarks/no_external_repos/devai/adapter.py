"""
DevAI data model and loader.

DevAI is a benchmark suite featuring 55 tasks with 365 hierarchical requirements.
Tasks span multiple domains including web development, data science, and automation.

Each task has:
- A user query describing what to build
- Hierarchical requirements with dependencies
- Preferences for how the task should be completed
- A domain classification

Requirements can depend on other requirements, creating a hierarchy that
reflects real-world software development where features often build on each other.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json


# DevAI domain categories
DEVAI_DOMAINS = [
    "web",          # Web application development
    "cli",          # Command-line tool development
    "data",         # Data processing and analysis
    "automation",   # Task automation scripts
    "api",          # API development
    "ml",           # Machine learning
    "testing",      # Testing tools and frameworks
    "devops",       # DevOps and deployment
]


@dataclass
class Requirement:
    """
    A requirement for a DevAI task.

    Requirements can have dependencies on other requirements,
    creating a hierarchical structure.

    Attributes:
        id: Unique requirement identifier within the task (e.g., 'R1', 'R1.1')
        description: Human-readable description of the requirement
        dependencies: List of requirement IDs this requirement depends on
        priority: Requirement priority (1=must-have, 2=should-have, 3=nice-to-have)
        category: Requirement category (functional, non-functional, constraint)
    """

    id: str
    description: str
    dependencies: list[str] = field(default_factory=list)
    priority: int = 1
    category: str = "functional"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "description": self.description,
            "dependencies": self.dependencies,
            "priority": self.priority,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Requirement":
        """Create a Requirement from a dictionary."""
        return cls(
            id=data.get("id", ""),
            description=data.get("description", ""),
            dependencies=data.get("dependencies", []),
            priority=data.get("priority", 1),
            category=data.get("category", "functional"),
        )


@dataclass
class Preference:
    """
    A preference for how a DevAI task should be completed.

    Preferences are softer constraints than requirements, indicating
    preferred approaches or technologies.

    Attributes:
        name: Preference name/identifier
        value: Preferred value or approach
        rationale: Reason for the preference
    """

    name: str
    value: str
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "name": self.name,
            "value": self.value,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Preference":
        """Create a Preference from a dictionary."""
        return cls(
            name=data.get("name", ""),
            value=data.get("value", ""),
            rationale=data.get("rationale", ""),
        )


@dataclass
class DevAITask:
    """
    Data model for a DevAI task.

    Attributes:
        id: Unique task identifier (e.g., 'devai-001')
        user_query: The user's request describing what to build
        requirements: Hierarchical list of requirements with dependencies
        preferences: List of preferences for how to complete the task
        domain: Task domain category (e.g., 'web', 'cli', 'data')
        description: Extended task description (optional)
        metadata: Additional task metadata
    """

    id: str
    user_query: str
    requirements: list[Requirement] = field(default_factory=list)
    preferences: list[Preference] = field(default_factory=list)
    domain: str = "general"
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate task fields after initialization."""
        # Normalize domain to lowercase
        if self.domain:
            self.domain = self.domain.lower()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "user_query": self.user_query,
            "requirements": [r.to_dict() for r in self.requirements],
            "preferences": [p.to_dict() for p in self.preferences],
            "domain": self.domain,
            "description": self.description,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DevAITask":
        """Create a DevAITask from a dictionary."""
        # Parse requirements
        requirements_data = data.get("requirements", [])
        requirements = [
            Requirement.from_dict(r) if isinstance(r, dict) else r
            for r in requirements_data
        ]

        # Parse preferences
        preferences_data = data.get("preferences", [])
        preferences = [
            Preference.from_dict(p) if isinstance(p, dict) else p
            for p in preferences_data
        ]

        return cls(
            id=data.get("id", ""),
            user_query=data.get("user_query", ""),
            requirements=requirements,
            preferences=preferences,
            domain=data.get("domain", "general"),
            description=data.get("description", ""),
            metadata=data.get("metadata", {}),
        )

    def get_root_requirements(self) -> list[Requirement]:
        """
        Get requirements with no dependencies (root of hierarchy).

        Returns:
            List of requirements that don't depend on other requirements.
        """
        return [r for r in self.requirements if not r.dependencies]

    def get_dependent_requirements(self, requirement_id: str) -> list[Requirement]:
        """
        Get requirements that depend on a given requirement.

        Args:
            requirement_id: The requirement ID to find dependents for.

        Returns:
            List of requirements that depend on the given requirement.
        """
        return [
            r for r in self.requirements
            if requirement_id in r.dependencies
        ]

    def get_requirement_count(self) -> int:
        """
        Get total number of requirements.

        Returns:
            Number of requirements in this task.
        """
        return len(self.requirements)


class DevAILoader:
    """
    Loader for DevAI tasks.

    Reads tasks from the DevAI dataset structure. Supports loading from
    individual JSON files or a combined manifest file.

    Expected directory structure (individual files):
        data_dir/
        ├── devai-001.json
        ├── devai-002.json
        └── ...

    Alternative structure (manifest):
        data_dir/
        ├── manifest.json
        └── tasks/
            ├── devai-001.json
            └── ...

    Alternative structure (combined):
        data_dir/
        └── tasks.json  (array of all tasks)
    """

    def __init__(self, data_dir: str | Path | None = None) -> None:
        """
        Initialize the loader.

        Args:
            data_dir: Path to the DevAI data directory.
                      If None, uses default path relative to this module.
        """
        if data_dir is None:
            # Default to a data directory relative to this module
            self.data_dir = Path(__file__).parent / "data"
        else:
            self.data_dir = Path(data_dir)

        self._tasks: list[DevAITask] = []
        self._loaded = False

    def load(self) -> list[DevAITask]:
        """
        Load all tasks from the data directory.

        Attempts to load from:
        1. tasks.json (combined file)
        2. manifest.json (manifest-based loading)
        3. Individual .json files in directory

        Returns:
            List of all DevAITask objects.
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
        # Load from individual files
        elif self.data_dir.exists():
            self._load_from_directory()

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
                    task = DevAITask.from_dict(task_data)
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

            tasks_dir = self.data_dir / "tasks"
            task_files = manifest.get("tasks", [])

            for task_file in task_files:
                task_path = tasks_dir / task_file
                if task_path.exists():
                    task = self._load_task_file(task_path)
                    if task:
                        self._tasks.append(task)

        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to load manifest: {e}")

    def _load_from_directory(self) -> None:
        """Load tasks from individual JSON files in the data directory."""
        # Also check tasks/ subdirectory
        search_dirs = [self.data_dir]
        tasks_subdir = self.data_dir / "tasks"
        if tasks_subdir.exists():
            search_dirs.append(tasks_subdir)

        for search_dir in search_dirs:
            for task_file in search_dir.glob("*.json"):
                # Skip manifest.json
                if task_file.name == "manifest.json":
                    continue
                # Skip combined tasks.json (handled separately)
                if task_file.name == "tasks.json":
                    continue

                task = self._load_task_file(task_file)
                if task:
                    self._tasks.append(task)

    def _load_task_file(self, task_path: Path) -> DevAITask | None:
        """Load a single task from a JSON file."""
        try:
            with open(task_path, encoding="utf-8") as f:
                data = json.load(f)

            # Generate ID from filename if not present
            if not data.get("id"):
                data["id"] = task_path.stem

            return DevAITask.from_dict(data)

        except (json.JSONDecodeError, IOError) as e:
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

    def filter_by_domain(self, domain: str) -> list[DevAITask]:
        """
        Filter tasks by domain.

        Args:
            domain: Domain to filter by (e.g., 'web', 'cli').

        Returns:
            List of tasks matching the specified domain.
        """
        if not self._loaded:
            self.load()
        domain_lower = domain.lower()
        return [
            task for task in self._tasks
            if task.domain.lower() == domain_lower
        ]

    def get_task(self, task_id: str) -> DevAITask | None:
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

    def get_domains(self) -> list[str]:
        """
        Get list of available domains.

        Returns:
            List of unique domains in the loaded dataset.
        """
        if not self._loaded:
            self.load()
        return list(set(task.domain for task in self._tasks))

    def task_count(self) -> int:
        """
        Get total number of loaded tasks.

        Returns:
            Number of tasks loaded.
        """
        if not self._loaded:
            self.load()
        return len(self._tasks)

    def total_requirement_count(self) -> int:
        """
        Get total number of requirements across all tasks.

        DevAI has 365 hierarchical requirements across 55 tasks.

        Returns:
            Total count of requirements.
        """
        if not self._loaded:
            self.load()
        return sum(task.get_requirement_count() for task in self._tasks)

    def filter_by_requirement_count(
        self,
        min_requirements: int | None = None,
        max_requirements: int | None = None,
    ) -> list[DevAITask]:
        """
        Filter tasks by number of requirements.

        Args:
            min_requirements: Minimum number of requirements (inclusive).
            max_requirements: Maximum number of requirements (inclusive).

        Returns:
            List of tasks matching the requirement count criteria.
        """
        if not self._loaded:
            self.load()

        result = []
        for task in self._tasks:
            count = task.get_requirement_count()
            if min_requirements is not None and count < min_requirements:
                continue
            if max_requirements is not None and count > max_requirements:
                continue
            result.append(task)

        return result


# Template directory for Harbor task generation
TEMPLATE_DIR = Path(__file__).parent / "templates"


class DevAIAdapter:
    """
    Adapter that converts DevAI tasks into Harbor task directories.

    Generates Harbor-compatible task structure with:
    - task.toml: Task configuration and metadata
    - instruction.md: Task instructions for the agent
    - environment/Dockerfile: Python 3.10+ with uv package manager
    - tests/test.sh: Verification script
    - tests/verify.py: Validates trajectory format against trajectory-schema.json
    - tests/trajectory-schema.json: JSON schema for trajectory validation

    Workspace generation matches DevAI's expected structure:
    benchmark/workspaces/{AGENT_NAME}/{task_name}/
    """

    NAME = "devai"

    def __init__(
        self,
        task_dir: str | Path,
        data_dir: str | Path | None = None,
    ) -> None:
        """
        Initialize the DevAI adapter.

        Args:
            task_dir: Output directory for generated Harbor tasks.
            data_dir: Path to DevAI data directory (optional).
        """
        self.task_dir = Path(task_dir)
        self.loader = DevAILoader(data_dir)
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
        Generate Dockerfile for DevAI tasks.

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

# Create working directories following DevAI workspace structure
# benchmark/workspaces/{AGENT_NAME}/{task_name}/
RUN mkdir -p /app /logs /workspace /tests /trajectory

# Set up Python environment with uv
WORKDIR /workspace

# Copy project files (if any)
COPY project /workspace/project

CMD ["/bin/bash"]
"""

    def _format_requirements_markdown(self, requirements: list[Requirement]) -> str:
        """
        Format requirements as markdown list with hierarchy info.

        Args:
            requirements: List of Requirement objects.

        Returns:
            Formatted markdown string.
        """
        if not requirements:
            return ""

        lines = ["### Requirements\n"]

        for req in requirements:
            # Priority indicators
            priority_map = {1: "🔴 Must-have", 2: "🟡 Should-have", 3: "🟢 Nice-to-have"}
            priority_str = priority_map.get(req.priority, "")

            # Format requirement line
            line = f"- **{req.id}**: {req.description}"
            if priority_str:
                line += f" ({priority_str})"

            # Add dependencies if present
            if req.dependencies:
                deps = ", ".join(req.dependencies)
                line += f"\n  - *Depends on*: {deps}"

            # Add category if not functional (default)
            if req.category != "functional":
                line += f"\n  - *Category*: {req.category}"

            lines.append(line)

        return "\n".join(lines)

    def _format_preferences_markdown(self, preferences: list[Preference]) -> str:
        """
        Format preferences as markdown list.

        Args:
            preferences: List of Preference objects.

        Returns:
            Formatted markdown string.
        """
        if not preferences:
            return ""

        lines = ["### Preferences\n"]

        for pref in preferences:
            line = f"- **{pref.name}**: {pref.value}"
            if pref.rationale:
                line += f"\n  - *Rationale*: {pref.rationale}"
            lines.append(line)

        return "\n".join(lines)

    def _create_instruction(self, task: DevAITask) -> str:
        """
        Create instruction.md content for the task.

        Args:
            task: The DevAITask instance.

        Returns:
            Rendered instruction content.
        """
        template_path = self.templates_dir / "instruction.md"

        # Format requirements and preferences as markdown
        requirements_text = self._format_requirements_markdown(task.requirements)
        preferences_text = self._format_preferences_markdown(task.preferences)

        context = {
            "id": task.id,
            "domain": task.domain,
            "user_query": task.user_query,
            "description": task.description or task.user_query,
            "requirements": requirements_text,
            "preferences": preferences_text,
            "requirement_count": len(task.requirements),
        }

        return self._render_template(template_path, context)

    def _create_task_toml(self, task: DevAITask) -> str:
        """
        Create task.toml content for the task.

        Args:
            task: The DevAITask instance.

        Returns:
            Task configuration as TOML string.
        """
        template_path = self.templates_dir / "task.toml"

        # Format tags
        tags = [
            "devai",
            task.domain,
        ]
        # Add requirement categories as tags
        categories = set(r.category for r in task.requirements)
        tags.extend(categories)
        tags_str = ", ".join(f'"{t}"' for t in tags)

        context = {
            "task_id": task.id,
            "domain": task.domain,
            "requirement_count": len(task.requirements),
            "tags": tags_str,
        }

        return self._render_template(template_path, context)

    def _create_trajectory_schema(self) -> dict[str, Any]:
        """
        Create JSON schema for trajectory validation.

        DevAI expects trajectories to follow a specific format.

        Returns:
            JSON schema dictionary.
        """
        return {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "DevAI Trajectory Schema",
            "type": "object",
            "required": ["task_id", "steps", "final_state"],
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The DevAI task ID"
                },
                "agent_name": {
                    "type": "string",
                    "description": "Name of the agent that produced this trajectory"
                },
                "steps": {
                    "type": "array",
                    "description": "List of steps taken by the agent",
                    "items": {
                        "type": "object",
                        "required": ["step_number", "action", "observation"],
                        "properties": {
                            "step_number": {
                                "type": "integer",
                                "minimum": 1
                            },
                            "action": {
                                "type": "object",
                                "properties": {
                                    "type": {
                                        "type": "string",
                                        "enum": ["command", "file_write", "file_read", "code_edit", "tool_call", "message"]
                                    },
                                    "content": {
                                        "type": "string"
                                    },
                                    "metadata": {
                                        "type": "object"
                                    }
                                }
                            },
                            "observation": {
                                "type": "object",
                                "properties": {
                                    "output": {
                                        "type": "string"
                                    },
                                    "success": {
                                        "type": "boolean"
                                    },
                                    "error": {
                                        "type": "string"
                                    }
                                }
                            },
                            "timestamp": {
                                "type": "string",
                                "format": "date-time"
                            }
                        }
                    }
                },
                "final_state": {
                    "type": "object",
                    "description": "Final state of the task completion",
                    "properties": {
                        "completed": {
                            "type": "boolean"
                        },
                        "requirements_met": {
                            "type": "object",
                            "description": "Map of requirement ID to completion status",
                            "additionalProperties": {
                                "type": "boolean"
                            }
                        },
                        "artifacts": {
                            "type": "array",
                            "description": "List of files or outputs produced",
                            "items": {
                                "type": "string"
                            }
                        }
                    }
                },
                "metadata": {
                    "type": "object",
                    "properties": {
                        "start_time": {
                            "type": "string",
                            "format": "date-time"
                        },
                        "end_time": {
                            "type": "string",
                            "format": "date-time"
                        },
                        "total_steps": {
                            "type": "integer"
                        }
                    }
                }
            }
        }

    def generate_task(self, task_id: str, local_task_id: str | None = None) -> Path:
        """
        Generate a Harbor task directory for a DevAI task.

        Args:
            task_id: DevAI task ID.
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

        # 4. Create empty project directory (matching DevAI workspace structure)
        project_dir = environment_dir / "project"
        project_dir.mkdir(parents=True, exist_ok=True)

        # 5. Copy/generate test.sh template
        test_sh_template = self.templates_dir / "test.sh"
        if test_sh_template.exists():
            test_sh_content = self._render_template(
                test_sh_template,
                {"id": task.id, "domain": task.domain},
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

        # 7. Write trajectory schema
        trajectory_schema = self._create_trajectory_schema()
        schema_path = tests_dir / "trajectory-schema.json"
        with open(schema_path, "w", encoding="utf-8") as f:
            json.dump(trajectory_schema, f, indent=2)

        # 8. Write ground truth with requirements
        ground_truth = {
            "task_id": task.id,
            "domain": task.domain,
            "user_query": task.user_query,
            "requirements": [r.to_dict() for r in task.requirements],
            "preferences": [p.to_dict() for p in task.preferences],
            "metadata": task.metadata,
        }
        ground_truth_path = tests_dir / "ground_truth.json"
        with open(ground_truth_path, "w", encoding="utf-8") as f:
            json.dump(ground_truth, f, indent=2)

        return out_dir

    def _generate_test_sh(self, task: DevAITask) -> str:
        """
        Generate test.sh content for verification.

        Args:
            task: The DevAITask instance.

        Returns:
            Shell script content.
        """
        return f"""#!/bin/bash
# DevAI Verification Script
# Task: {task.id}
# Domain: {task.domain}

set -uo pipefail

echo "=== DevAI Verifier ==="
echo "Task ID: {task.id}"
echo "Domain: {task.domain}"
echo "Requirements: {len(task.requirements)}"

# Create output directories
mkdir -p /logs/verifier

# Check for trajectory file
TRAJECTORY_FILE="/trajectory/trajectory.json"
if [ ! -f "$TRAJECTORY_FILE" ]; then
    # Check alternative locations
    if [ -f "/workspace/trajectory.json" ]; then
        TRAJECTORY_FILE="/workspace/trajectory.json"
    elif [ -f "/app/trajectory.json" ]; then
        TRAJECTORY_FILE="/app/trajectory.json"
    fi
fi

# Check for ground truth
if [ ! -f /tests/ground_truth.json ]; then
    echo "ERROR: ground_truth.json not found"
    echo '{{"score": 0.0, "error": "Missing ground truth"}}' > /logs/verifier/reward.json
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

echo "Trajectory file: $TRAJECTORY_FILE"

# Run Python verifier to validate trajectory and generate reward.json
python3 /tests/verify.py \\
    --trajectory "$TRAJECTORY_FILE" \\
    --schema /tests/trajectory-schema.json \\
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
        Generate verify.py content for validating trajectory format.

        Returns:
            Python script content.
        """
        return '''#!/usr/bin/env python3
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
'''
