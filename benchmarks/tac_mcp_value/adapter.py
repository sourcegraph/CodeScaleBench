"""
TheAgentCompany (TAC) data model, loader, and adapter.

TAC is a benchmark evaluating AI agents on real-world professional tasks
across multiple roles: SWE (Software Engineering), PM (Project Management),
DS (Data Science), HR, Finance, and Admin.

Key concepts:
- TAC tasks run in pre-built Docker images with built-in evaluation
- /utils/eval.py is the standard evaluator inside TAC containers
- MCP configuration can be injected via environment variables
- Verification outputs checkpoint-based scores

The adapter generates thin wrapper tasks for Harbor that delegate to TAC's
existing evaluation infrastructure. The verifier wraps TAC's checkpoint scoring
and outputs task completion as the primary metric.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json


# TAC Docker image registry and version
TAC_REGISTRY = "ghcr.io/theagentcompany"
TAC_VERSION = "1.0.0"

# Valid TAC roles
TAC_ROLES = ("SWE", "PM", "DS", "HR", "Finance", "Admin")


@dataclass
class TACTask:
    """
    Data model for a TAC (TheAgentCompany) task instance.

    TAC tasks are professional work simulations evaluated via checkpoint-based
    scoring. Tasks span multiple roles including software engineering,
    project management, data science, HR, finance, and admin.

    Attributes:
        id: Unique Harbor task identifier (e.g., 'tac-implement-hyperloglog')
        tac_id: Original TAC task ID (e.g., 'sde-implement-hyperloglog')
        role: Task role category (SWE, PM, DS, HR, Finance, Admin)
        title: Human-readable task title
        description: Brief description of the task
        task_md_path: Path to original task.md within TAC container
        docker_image: Full Docker image name for this task
        language: Primary programming language (if applicable)
        difficulty: Task difficulty (easy, medium, hard)
        mcp_value: Expected MCP benefit level (low, medium, high, very-high)
        grading_type: Type of evaluation (deterministic, llm-based, mixed)
        dependencies: List of TAC server dependencies (gitlab, rocketchat, etc.)
        metadata: Additional task metadata
    """

    id: str
    tac_id: str
    role: str
    title: str
    description: str = ""
    task_md_path: str = "/instruction/task.md"
    docker_image: str = ""
    language: str = ""
    difficulty: str = "medium"
    mcp_value: str = "medium"
    grading_type: str = "deterministic"
    dependencies: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize values after initialization."""
        # Normalize role to uppercase
        self.role = self.role.upper()
        if self.role not in TAC_ROLES:
            # Default to SWE for sde-* tasks
            if self.tac_id.startswith("sde-"):
                self.role = "SWE"
            else:
                self.role = "SWE"  # Default

        # Normalize difficulty to lowercase
        self.difficulty = self.difficulty.lower()

        # Normalize mcp_value to lowercase with hyphen
        self.mcp_value = self.mcp_value.lower().replace("_", "-")

        # Generate Docker image if not provided
        if not self.docker_image:
            self.docker_image = f"{TAC_REGISTRY}/{self.tac_id}-image:{TAC_VERSION}"

        # Generate Harbor ID if not provided
        if not self.id:
            # Convert tac_id to harbor_id: sde-implement-hyperloglog -> tac-implement-hyperloglog
            if self.tac_id.startswith("sde-"):
                self.id = "tac-" + self.tac_id[4:]
            else:
                self.id = "tac-" + self.tac_id

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "tac_id": self.tac_id,
            "role": self.role,
            "title": self.title,
            "description": self.description,
            "task_md_path": self.task_md_path,
            "docker_image": self.docker_image,
            "language": self.language,
            "difficulty": self.difficulty,
            "mcp_value": self.mcp_value,
            "grading_type": self.grading_type,
            "dependencies": self.dependencies,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TACTask":
        """Create a TACTask from a dictionary."""
        return cls(
            id=data.get("id", data.get("harbor_id", "")),
            tac_id=data.get("tac_id", data.get("task_id", "")),
            role=data.get("role", "SWE"),
            title=data.get("title", data.get("name", "")),
            description=data.get("description", ""),
            task_md_path=data.get("task_md_path", "/instruction/task.md"),
            docker_image=data.get("docker_image", data.get("image", "")),
            language=data.get("language", ""),
            difficulty=data.get("difficulty", "medium"),
            mcp_value=data.get("mcp_value", "medium"),
            grading_type=data.get("grading_type", "deterministic"),
            dependencies=data.get("dependencies", []),
            metadata=data.get("metadata", {}),
        )

    def get_docker_image(self) -> str:
        """Get the full Docker image name for this task."""
        return self.docker_image

    def requires_server(self, server: str) -> bool:
        """Check if task requires a specific TAC server dependency."""
        return server.lower() in [d.lower() for d in self.dependencies]

    def is_code_focused(self) -> bool:
        """Check if task is primarily code-focused (SWE tasks)."""
        return self.role == "SWE"


class TACLoader:
    """
    Loader for TAC (TheAgentCompany) task instances.

    Reads tasks from configuration files or uses curated task list.
    Supports filtering by role, difficulty, and MCP value.

    Expected directory structure:
        data_dir/
        ├── tasks.json          (combined file with all tasks)
        └── manifest.json       (or task manifest)

    Alternative: Use built-in curated tasks list.
    """

    # Curated TAC tasks for MCP value evaluation
    CURATED_TASKS = [
        TACTask(
            id="tac-implement-hyperloglog",
            tac_id="sde-implement-hyperloglog",
            role="SWE",
            title="Implement HyperLogLog Algorithm",
            description="Implement HyperLogLog in bustub database system",
            language="cpp",
            difficulty="hard",
            mcp_value="high",
            grading_type="deterministic",
            dependencies=["gitlab"],
        ),
        TACTask(
            id="tac-buffer-pool-manager",
            tac_id="sde-implement-buffer-pool-manager-bustub",
            role="SWE",
            title="Implement Buffer Pool Manager",
            description="Implement buffer pool manager in bustub",
            language="cpp",
            difficulty="hard",
            mcp_value="high",
            grading_type="deterministic",
            dependencies=["gitlab"],
        ),
        TACTask(
            id="tac-dependency-change",
            tac_id="sde-dependency-change-1",
            role="SWE",
            title="Update Dependency Versions",
            description="Update Python dependency versions in OpenHands",
            language="python",
            difficulty="medium",
            mcp_value="medium",
            grading_type="deterministic",
            dependencies=["gitlab"],
        ),
        TACTask(
            id="tac-find-in-codebase-1",
            tac_id="sde-find-answer-in-codebase-1",
            role="SWE",
            title="Find PR in Codebase (Context Window)",
            description="Find PR that improved llama3.1 context window",
            language="cpp",
            difficulty="medium",
            mcp_value="very-high",
            grading_type="llm-based",
            dependencies=["gitlab", "rocketchat"],
        ),
        TACTask(
            id="tac-find-in-codebase-2",
            tac_id="sde-find-answer-in-codebase-2",
            role="SWE",
            title="Find PR in Codebase (File Change)",
            description="Find PR that changed a specific file",
            language="cpp",
            difficulty="medium",
            mcp_value="very-high",
            grading_type="llm-based",
            dependencies=["gitlab", "rocketchat"],
        ),
        TACTask(
            id="tac-copilot-arena-endpoint",
            tac_id="sde-copilot-arena-server-new-endpoint",
            role="SWE",
            title="Add API Endpoint",
            description="Add new endpoint to copilot-arena-server",
            language="python",
            difficulty="medium",
            mcp_value="medium-high",
            grading_type="deterministic",
            dependencies=["gitlab"],
        ),
        TACTask(
            id="tac-write-unit-test",
            tac_id="sde-write-a-unit-test-for-search_file-function",
            role="SWE",
            title="Write Unit Test",
            description="Write unit test for search_file function",
            language="python",
            difficulty="medium",
            mcp_value="high",
            grading_type="deterministic",
            dependencies=["gitlab"],
        ),
        TACTask(
            id="tac-troubleshoot-dev-setup",
            tac_id="sde-troubleshoot-dev-setup",
            role="SWE",
            title="Troubleshoot Dev Setup",
            description="Fix broken development environment",
            language="python",
            difficulty="medium",
            mcp_value="medium",
            grading_type="mixed",
            dependencies=["gitlab", "rocketchat"],
        ),
    ]

    def __init__(self, data_dir: str | Path | None = None) -> None:
        """
        Initialize the loader.

        Args:
            data_dir: Path to the TAC data directory.
                      If None, uses curated task list.
        """
        if data_dir is None:
            # Default to curated tasks
            self.data_dir = None
        else:
            self.data_dir = Path(data_dir)

        self._tasks: list[TACTask] = []
        self._loaded = False

    def load(self) -> list[TACTask]:
        """
        Load all tasks.

        Attempts to load from:
        1. tasks.json (combined file) if data_dir provided
        2. manifest.json if data_dir provided
        3. Built-in curated tasks list

        Returns:
            List of all TACTask objects.
        """
        if self._loaded:
            return self._tasks

        self._tasks = []

        if self.data_dir and self.data_dir.exists():
            # Try loading from combined tasks.json
            tasks_file = self.data_dir / "tasks.json"
            if tasks_file.exists():
                self._load_from_combined_file(tasks_file)
            # Try loading from manifest
            elif (self.data_dir / "manifest.json").exists():
                self._load_from_manifest(self.data_dir / "manifest.json")

        # Fall back to curated tasks if no external data loaded
        if not self._tasks:
            self._tasks = list(self.CURATED_TASKS)

        self._loaded = True
        return self._tasks

    def _load_from_combined_file(self, tasks_file: Path) -> None:
        """Load tasks from a single combined JSON file."""
        try:
            with open(tasks_file, encoding="utf-8") as f:
                data = json.load(f)

            # Handle both array of tasks and object with 'tasks' key
            tasks_data: list[dict[str, Any]]
            if isinstance(data, list):
                tasks_data = data
            elif isinstance(data, dict):
                tasks_key = data.get("tasks", data.get("instances"))
                tasks_data = tasks_key if tasks_key is not None else []
            else:
                return

            for task_data in tasks_data:
                try:
                    task = TACTask.from_dict(task_data)
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
                if isinstance(instance_entry, dict):
                    task = TACTask.from_dict(instance_entry)
                    self._tasks.append(task)

        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to load manifest: {e}")

    def all_ids(self) -> list[str]:
        """
        Get all task IDs.

        Returns:
            List of all Harbor task IDs in the loaded dataset.
        """
        if not self._loaded:
            self.load()
        return [task.id for task in self._tasks]

    def get_task(self, task_id: str) -> TACTask | None:
        """
        Get a specific task by ID (Harbor ID or TAC ID).

        Args:
            task_id: The task ID to look up (supports both Harbor and TAC IDs).

        Returns:
            The task if found, None otherwise.
        """
        if not self._loaded:
            self.load()
        for task in self._tasks:
            if task.id == task_id or task.tac_id == task_id:
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

    def filter_by_role(self, role: str) -> list[TACTask]:
        """
        Filter tasks by role.

        Args:
            role: Role to filter by (SWE, PM, DS, HR, Finance, Admin).

        Returns:
            List of tasks matching the role.
        """
        if not self._loaded:
            self.load()
        role_upper = role.upper()
        return [task for task in self._tasks if task.role == role_upper]

    def filter_by_difficulty(self, difficulty: str) -> list[TACTask]:
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
            if task.difficulty == difficulty_lower
        ]

    def filter_by_mcp_value(self, mcp_value: str) -> list[TACTask]:
        """
        Filter tasks by expected MCP value.

        Args:
            mcp_value: MCP value level (low, medium, high, very-high).

        Returns:
            List of tasks matching the MCP value level.
        """
        if not self._loaded:
            self.load()
        mcp_value_normalized = mcp_value.lower().replace("_", "-")
        return [
            task for task in self._tasks
            if task.mcp_value == mcp_value_normalized
        ]

    def filter_by_grading_type(self, grading_type: str) -> list[TACTask]:
        """
        Filter tasks by grading type.

        Args:
            grading_type: Grading type (deterministic, llm-based, mixed).

        Returns:
            List of tasks matching the grading type.
        """
        if not self._loaded:
            self.load()
        grading_type_lower = grading_type.lower()
        return [
            task for task in self._tasks
            if task.grading_type == grading_type_lower
        ]

    def get_roles(self) -> list[str]:
        """
        Get unique roles present in the dataset.

        Returns:
            Sorted list of unique role names.
        """
        if not self._loaded:
            self.load()
        return sorted(set(task.role for task in self._tasks))

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
                "roles": [],
                "difficulty_distribution": {},
                "mcp_value_distribution": {},
            }

        return {
            "total_tasks": len(self._tasks),
            "roles": self.get_roles(),
            "role_distribution": {
                role: len(self.filter_by_role(role))
                for role in self.get_roles()
            },
            "difficulty_distribution": {
                "easy": len([t for t in self._tasks if t.difficulty == "easy"]),
                "medium": len([t for t in self._tasks if t.difficulty == "medium"]),
                "hard": len([t for t in self._tasks if t.difficulty == "hard"]),
            },
            "mcp_value_distribution": {
                "low": len([t for t in self._tasks if t.mcp_value == "low"]),
                "medium": len([t for t in self._tasks if t.mcp_value == "medium"]),
                "medium-high": len([t for t in self._tasks if t.mcp_value == "medium-high"]),
                "high": len([t for t in self._tasks if t.mcp_value == "high"]),
                "very-high": len([t for t in self._tasks if t.mcp_value == "very-high"]),
            },
            "grading_type_distribution": {
                "deterministic": len([t for t in self._tasks if t.grading_type == "deterministic"]),
                "llm-based": len([t for t in self._tasks if t.grading_type == "llm-based"]),
                "mixed": len([t for t in self._tasks if t.grading_type == "mixed"]),
            },
        }


# Template directory for Harbor task generation
TEMPLATE_DIR = Path(__file__).parent / "templates"


class TACAdapter:
    """
    Thin wrapper adapter that generates Harbor-compatible tasks from TAC.

    This adapter generates Harbor task metadata (task.toml, instruction.md)
    while delegating actual evaluation to TAC's existing infrastructure.
    The verifier wraps TAC's /utils/eval.py checkpoint scoring.

    MCP configuration is injected via environment variables and setup scripts
    in task.toml.

    Generated Harbor task structure:
    - task.toml: Task configuration with MCP setup scripts
    - instruction.md: Task instructions for the agent
    - environment/Dockerfile: Wraps TAC Docker image
    - tests/test.sh: Verification script that wraps TAC's eval.py
    - tests/ground_truth.json: Reference data for the task
    """

    NAME = "tac_mcp_value"

    def __init__(
        self,
        task_dir: str | Path,
        data_dir: str | Path | None = None,
    ) -> None:
        """
        Initialize the TAC adapter.

        Args:
            task_dir: Output directory for generated Harbor tasks.
            data_dir: Path to TAC data directory (optional).
        """
        self.task_dir = Path(task_dir)
        self.loader = TACLoader(data_dir)
        self.templates_dir = TEMPLATE_DIR

    def _render_template(self, template_path: Path, context: dict[str, Any]) -> str:
        """
        Simple template rendering by replacing ${key} and {key} placeholders.

        Args:
            template_path: Path to the template file.
            context: Dictionary of placeholder values.

        Returns:
            Rendered template string.
        """
        content = template_path.read_text()
        for template_key, value in context.items():
            # Replace both ${KEY} and {key} patterns
            content = content.replace(f"${{{template_key}}}", str(value))
            content = content.replace(f"{{{template_key}}}", str(value))
        return content

    def _generate_mcp_setup_script(self) -> str:
        """
        Generate MCP configuration setup script.

        This script is embedded in task.toml and runs during container setup
        to configure Sourcegraph MCP if credentials are provided.

        Returns:
            Shell script content for MCP setup.
        """
        return '''#!/bin/bash
# Setup Sourcegraph MCP if credentials provided
if [ -n "$SOURCEGRAPH_ACCESS_TOKEN" ] && [ -n "$SOURCEGRAPH_URL" ]; then
  echo "Setting up Sourcegraph MCP configuration..."
  mkdir -p /root/.config/claude

  cat > /root/.config/claude/mcp.json << 'MCPEOF'
{
  "mcpServers": {
    "sourcegraph": {
      "command": "npx",
      "args": ["-y", "@sourcegraph/mcp-server"],
      "env": {
        "SRC_ACCESS_TOKEN": "${SOURCEGRAPH_ACCESS_TOKEN}",
        "SOURCEGRAPH_URL": "${SOURCEGRAPH_URL}"
      }
    }
  }
}
MCPEOF

  # Substitute environment variables
  sed -i 's|\\${SOURCEGRAPH_ACCESS_TOKEN}|'"$SOURCEGRAPH_ACCESS_TOKEN"'|g' /root/.config/claude/mcp.json
  sed -i 's|\\${SOURCEGRAPH_URL}|'"$SOURCEGRAPH_URL"'|g' /root/.config/claude/mcp.json

  echo "MCP configuration created"
else
  echo "No Sourcegraph credentials provided, MCP disabled"
fi
exit 0
'''

    def _generate_dockerfile(self, task: TACTask) -> str:
        """
        Generate Dockerfile for TAC tasks.

        Wraps TAC's pre-built Docker image with Harbor integration.

        Args:
            task: The TACTask instance.

        Returns:
            Dockerfile content as string.
        """
        template_path = self.templates_dir / "Dockerfile.template"

        context = {
            "TASK_NAME": task.tac_id,
            "TASK_ID": task.id,
            "TAC_IMAGE": task.docker_image,
        }

        if template_path.exists():
            return self._render_template(template_path, context)

        # Fallback inline template
        return f"""# TAC Task Wrapper Environment
# This Dockerfile wraps TheAgentCompany's pre-built task images for Harbor integration

ARG TAC_IMAGE={task.docker_image}
FROM ${{TAC_IMAGE}}

# TAC images are already set up with:
# - /utils/ containing init.sh, eval.py, evaluator.py.enc, common.py, scoring.py
# - /instruction/ containing task.md
# - /workspace/ as the working directory

# Create logs directory for Harbor compatibility
RUN mkdir -p /logs

# Copy our test wrapper script
COPY tests/test.sh /workspace/tests/test.sh
RUN chmod +x /workspace/tests/test.sh

# Set working directory
WORKDIR /workspace

# Environment variables for TAC server connection
# These should be provided at runtime
ENV TAC_SERVER_HOSTNAME=localhost
ENV LITELLM_API_KEY=""
ENV LITELLM_BASE_URL=""
ENV LITELLM_MODEL=""
ENV DECRYPTION_KEY="theagentcompany is all you need"

# Initialize TAC task environment on container start
CMD ["bash"]
"""

    def _generate_instruction(self, task: TACTask) -> str:
        """
        Generate instruction.md content.

        Args:
            task: The TACTask instance.

        Returns:
            Instruction content as string.
        """
        template_path = self.templates_dir / "instruction.md.template"

        # Determine task type based on grading
        task_type_map = {
            "deterministic": "Code Implementation",
            "llm-based": "Information Retrieval",
            "mixed": "Mixed (Implementation + Analysis)",
        }
        task_type = task_type_map.get(task.grading_type, "General")

        # MCP rationale based on mcp_value
        mcp_rationale_map = {
            "very-high": "This task requires deep code search and cross-repository understanding.",
            "high": "This task benefits significantly from code intelligence and navigation.",
            "medium-high": "This task can leverage code search for faster implementation.",
            "medium": "This task may benefit from code context awareness.",
            "low": "This task has limited MCP benefit.",
        }
        mcp_rationale = mcp_rationale_map.get(task.mcp_value, "MCP may provide assistance.")

        # Original task MD placeholder - agent will read from /instruction/task.md
        original_task_md = f"""**Task instructions are provided in the TAC environment.**

Read the task from: `/instruction/task.md`

The task environment is pre-configured with all necessary dependencies and tools.
"""

        context = {
            "TASK_TITLE": task.title,
            "TASK_ID": task.id,
            "DIFFICULTY": task.difficulty,
            "TASK_TYPE": task_type,
            "TASK_DESCRIPTION": task.description,
            "MCP_RATIONALE": mcp_rationale,
            "ORIGINAL_TASK_MD": original_task_md,
            "LANGUAGE": task.language or "Multiple",
        }

        if template_path.exists():
            return self._render_template(template_path, context)

        # Fallback inline template
        return f"""# {task.title}

**Repository:** TheAgentCompany Task
**Difficulty:** {task.difficulty}
**Category:** tac_mcp_value
**Task Type:** {task_type}

## Description

{task.description}

**Why this may benefit from MCP:** {mcp_rationale}

## Task

Complete the task as described below:

---

{original_task_md}

---

## Success Criteria

Task is evaluated using TheAgentCompany's built-in evaluator with checkpoint-based scoring.
A score > 0 indicates partial or full success.

## Notes

- This task uses TheAgentCompany's pre-built environment
- TAC servers may be required (see TAC_SERVER_HOSTNAME environment variable)
- Review checkpoints.md in TAC source for detailed grading criteria
"""

    def _generate_task_toml(self, task: TACTask) -> str:
        """
        Generate task.toml content with MCP configuration.

        Args:
            task: The TACTask instance.

        Returns:
            Task configuration as TOML string.
        """
        template_path = self.templates_dir / "task.toml.template"

        mcp_setup_script = self._generate_mcp_setup_script()

        context = {
            "TASK_ID": task.id,
            "TASK_DESCRIPTION": task.description,
            "LANGUAGE": task.language or "mixed",
            "DIFFICULTY": task.difficulty,
        }

        if template_path.exists():
            return self._render_template(template_path, context)

        # Fallback inline template with MCP setup
        return f'''version = "1.0"

[metadata]
author_name = "TheAgentCompany Adapter"
author_email = "theagentcompany@cmu.edu"
task_id = "{task.id}"
category = "tac_mcp_value"
language = "{task.language or "mixed"}"
difficulty = "{task.difficulty}"
tags = ["theagentcompany", "mcp-value"]

[verifier]
timeout_sec = 2400.0
command = "bash /workspace/tests/test.sh"

[agent]
timeout_sec = 2400.0

[environment]
build_timeout_sec = 1800.0
cpus = 4
memory = "8G"
storage = "20G"

[environment.setup_scripts]
mcp_config = """
{mcp_setup_script}
"""
'''

    def _generate_test_sh(self, task: TACTask) -> str:
        """
        Generate test.sh verification script.

        Args:
            task: The TACTask instance.

        Returns:
            Shell script content.
        """
        template_path = self.templates_dir / "test.sh.template"

        context = {
            "TASK_ID": task.id,
            "TAC_ID": task.tac_id,
        }

        if template_path.exists():
            return self._render_template(template_path, context)

        # Fallback inline template
        return f'''#!/bin/bash
# TAC Task Verification Wrapper
# Task: {task.id}
# Runs TheAgentCompany's evaluator and converts to Harbor-compatible exit code

set -e

# Output paths
TRAJECTORY_PATH="${{TRAJECTORY_PATH:-/logs/trajectory.jsonl}}"
OUTPUT_PATH="/logs/tac_result.json"

# Create empty trajectory if not exists (TAC evaluator expects it)
if [ ! -f "$TRAJECTORY_PATH" ]; then
    echo '[]' > "$TRAJECTORY_PATH"
fi

# Source TAC environment if needed
if [ -n "$TAC_SERVER_HOSTNAME" ]; then
    export SERVER_HOSTNAME="$TAC_SERVER_HOSTNAME"
fi

# Run TAC evaluator
echo "Running TAC evaluator..."
cd /utils

# Check if we need to run init first (for tasks that require it)
if [ -f "/utils/init.sh" ] && [ ! -f "/workspace/.tac_initialized" ]; then
    echo "Initializing TAC task environment..."
    bash /utils/init.sh || true
    touch /workspace/.tac_initialized
fi

# Run the evaluator with decryption key
DECRYPTION_KEY="${{DECRYPTION_KEY:-theagentcompany is all you need}}" \\
python_default /utils/eval.py \\
    --trajectory_path "$TRAJECTORY_PATH" \\
    --output_path "$OUTPUT_PATH" \\
    2>&1 || {{
    echo "TAC evaluator failed, attempting alternative evaluation..."
    # Some tasks may not need full TAC eval infrastructure
    echo '{{"score": 0, "checkpoints": [], "error": "Evaluator failed"}}' > "$OUTPUT_PATH"
}}

# Parse result and determine pass/fail
if [ -f "$OUTPUT_PATH" ]; then
    SCORE=$(python3 -c "import json; print(json.load(open('$OUTPUT_PATH')).get('score', 0))" 2>/dev/null || echo "0")
    echo "TAC Score: $SCORE"

    # Copy result to Harbor's expected location
    cp "$OUTPUT_PATH" /logs/reward.json 2>/dev/null || true

    # Any score > 0 is considered a pass for comparison purposes
    if [ "$SCORE" != "0" ] && [ -n "$SCORE" ]; then
        echo "Task passed with score: $SCORE"
        exit 0
    else
        echo "Task failed with score: $SCORE"
        exit 1
    fi
else
    echo "No result file generated"
    exit 1
fi
'''

    def _generate_verify_py(self, task: TACTask) -> str:
        """
        Generate verify.py for converting TAC evaluation to Harbor format.

        Args:
            task: The TACTask instance.

        Returns:
            Python script content.
        """
        return f'''#!/usr/bin/env python3
"""
TAC Verifier

Converts TheAgentCompany's checkpoint-based evaluation to Harbor reward format.
"""

import argparse
import json
from pathlib import Path
from typing import Any


def convert_tac_result(tac_result: dict[str, Any]) -> dict[str, Any]:
    """
    Convert TAC evaluation result to Harbor reward format.

    Args:
        tac_result: TAC evaluation output with checkpoints and score.

    Returns:
        Harbor-compatible reward dictionary.
    """
    score = tac_result.get("score", 0)
    checkpoints = tac_result.get("checkpoints", [])
    error = tac_result.get("error")

    # Compute metrics
    total_checkpoints = len(checkpoints) if checkpoints else 0
    passed_checkpoints = sum(1 for cp in checkpoints if cp.get("passed", False))

    result = {{
        "score": float(score),
        "task_id": "{task.id}",
        "metrics": {{
            "tac_score": score,
            "total_checkpoints": total_checkpoints,
            "passed_checkpoints": passed_checkpoints,
            "checkpoint_rate": passed_checkpoints / total_checkpoints if total_checkpoints > 0 else 0.0,
        }},
        "checkpoints": checkpoints,
    }}

    if error:
        result["error"] = error

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="TAC Verifier")
    parser.add_argument(
        "--tac-result",
        default="/logs/tac_result.json",
        help="Path to TAC evaluation result",
    )
    parser.add_argument(
        "--output",
        default="/logs/reward.json",
        help="Path to output reward JSON",
    )
    args = parser.parse_args()

    tac_result_path = Path(args.tac_result)
    output_path = Path(args.output)

    # Read TAC result
    if not tac_result_path.exists():
        result = {{"score": 0.0, "error": f"TAC result not found: {{tac_result_path}}"}}
        output_path.write_text(json.dumps(result, indent=2))
        print(f"Error: {{result['error']}}")
        return

    try:
        with open(tac_result_path, "r", encoding="utf-8") as f:
            tac_result = json.load(f)
    except json.JSONDecodeError as e:
        result = {{"score": 0.0, "error": f"Failed to parse TAC result: {{e}}"}}
        output_path.write_text(json.dumps(result, indent=2))
        print(f"Error: {{result['error']}}")
        return

    # Convert and write
    result = convert_tac_result(tac_result)
    output_path.write_text(json.dumps(result, indent=2))

    print(f"Verification complete:")
    print(f"  Score: {{result.get('score', 0.0)}}")
    metrics = result.get("metrics", {{}})
    print(f"  Checkpoints: {{metrics.get('passed_checkpoints', 0)}}/{{metrics.get('total_checkpoints', 0)}}")


if __name__ == "__main__":
    main()
'''

    def _create_ground_truth(self, task: TACTask) -> dict[str, Any]:
        """
        Create ground truth JSON for verification.

        Args:
            task: The TACTask instance.

        Returns:
            Ground truth dictionary.
        """
        return {
            "task_id": task.id,
            "tac_id": task.tac_id,
            "role": task.role,
            "title": task.title,
            "description": task.description,
            "docker_image": task.docker_image,
            "language": task.language,
            "difficulty": task.difficulty,
            "mcp_value": task.mcp_value,
            "grading_type": task.grading_type,
            "dependencies": task.dependencies,
            "metadata": task.metadata,
        }

    def generate_task(self, task_id: str, local_task_id: str | None = None) -> Path:
        """
        Generate a Harbor task directory for a TAC task.

        Args:
            task_id: TAC task ID (Harbor ID or TAC ID).
            local_task_id: Optional local directory name for the task.
                          Defaults to task's Harbor ID if not provided.

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
        out_dir_name = local_task_id if local_task_id else task.id
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
        role_filter: str | None = None,
        limit: int | None = None,
    ) -> list[Path]:
        """
        Generate Harbor tasks for all or filtered TAC tasks.

        Args:
            role_filter: Optional role to filter by (SWE, PM, DS, HR, Finance, Admin).
            limit: Optional limit on number of tasks to generate.

        Returns:
            List of paths to generated task directories.
        """
        self.loader.load()

        if role_filter:
            tasks = self.loader.filter_by_role(role_filter)
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
