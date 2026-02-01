"""
DI-Bench Adapter for Harbor

Converts DI-Bench dependency inference tasks into Harbor task structure.
"""

import json
import shutil
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, List, Optional

import importlib.util

# Add src to path for imports
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))


def _import_module_from_file(module_name: str, file_path: Path):
    """Import a module from a file path without triggering package __init__."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module {module_name} from {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# Import models directly from their files
difficulty_module = _import_module_from_file(
    "harbor.models.difficulty",
    src_path / "harbor" / "models" / "difficulty.py"
)
Difficulty = difficulty_module.Difficulty

task_config_module = _import_module_from_file(
    "harbor.models.task.config",
    src_path / "harbor" / "models" / "task" / "config.py"
)
AgentConfig = task_config_module.AgentConfig
EnvironmentConfig = task_config_module.EnvironmentConfig
TaskConfig = task_config_module.TaskConfig
VerifierConfig = task_config_module.VerifierConfig

task_paths_module = _import_module_from_file(
    "harbor.models.task.paths",
    src_path / "harbor" / "models" / "task" / "paths.py"
)
TaskPaths = task_paths_module.TaskPaths

ADAPTER_NAME = "dibench"
TEMPLATE_DIR = Path(__file__).parent / "templates"


@dataclass
class DIBenchInstance:
    """Represents a DI-Bench repository instance."""
    instance_id: str
    metadata: dict
    language: str
    act_command: str
    ci_file: str
    patch: str
    build_files: List[str]
    env_specs: dict

    @classmethod
    def from_dict(cls, data: dict) -> "DIBenchInstance":
        """Create instance from dictionary."""
        return cls(
            instance_id=data["instance_id"],
            metadata=data.get("metadata", {}),
            language=data["language"],
            act_command=data["act_command"],
            ci_file=data["ci_file"],
            patch=data.get("patch", ""),
            build_files=data.get("build_files", []),
            env_specs=data.get("env_specs", {}),
        )


class RequireNameMeta(type(ABC)):
    def __init__(cls, name, bases, dct):
        type.__init__(cls, name, bases, dct)

        if name != "BaseAdapter" and not hasattr(cls, "NAME"):
            raise TypeError(f"Class {name} must define a class property 'NAME'.")


class BaseAdapter(ABC, metaclass=RequireNameMeta):
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


class DIBenchLoader:
    """Loads DI-Bench instances from dataset file."""

    def __init__(self, dataset_path: Optional[Path] = None):
        """
        Initialize the loader.

        Args:
            dataset_path: Path to JSONL dataset file. If None, instances must be
                         loaded from repo_instances_dir directly.
        """
        self.dataset_path = dataset_path
        self._instances = {}

        if dataset_path and dataset_path.exists():
            self._load_dataset()

    def _load_dataset(self):
        """Load instances from JSONL dataset file."""
        with open(self.dataset_path, "r") as f:
            for line in f:
                data = json.loads(line.strip())
                instance = DIBenchInstance.from_dict(data)
                key = f"{instance.language}/{instance.instance_id}"
                self._instances[key] = instance

    def load(self, task_id: str) -> DIBenchInstance:
        """
        Load a single instance by task_id.

        Args:
            task_id: Format "language/instance_id"
        """
        if task_id in self._instances:
            return self._instances[task_id]
        raise KeyError(f"Instance not found: {task_id}")

    def all_ids(self) -> List[str]:
        """Return all task IDs."""
        return sorted(self._instances.keys())


class DIBenchAdapter(BaseAdapter):
    """Adapter that converts DI-Bench tasks into Harbor task directories."""

    NAME = "dibench"

    def __init__(
        self,
        task_dir: Path,
        repo_instances_dir: Path,
        dataset_path: Optional[Path] = None,
        **kwargs
    ):
        """
        Initialize DI-Bench adapter.

        Args:
            task_dir: Output directory for Harbor tasks
            repo_instances_dir: Directory containing extracted DI-Bench repositories
            dataset_path: Optional path to JSONL dataset file
            **kwargs: Additional arguments
        """
        super().__init__(**kwargs)
        self.task_dir = Path(task_dir)
        self.repo_instances_dir = Path(repo_instances_dir)
        self.loader = DIBenchLoader(dataset_path)
        self.templates_dir = TEMPLATE_DIR

    def _get_repo_path(self, language: str, instance_id: str) -> Path:
        """Get path to repository instance."""
        return self.repo_instances_dir / language.lower() / instance_id

    def _render_template(self, template_path: Path, context: dict) -> str:
        """Simple template rendering by replacing {key} placeholders."""
        content = template_path.read_text()
        for key, value in context.items():
            content = content.replace(f"{{{key}}}", str(value))
            content = content.replace(f"{{{{ {key} }}}}", str(value))
        return content

    def _create_instruction(
        self, instance: DIBenchInstance, repo_path: Path
    ) -> str:
        """Create instruction.md content."""
        template_path = self.templates_dir / "instruction.md"

        # Build instruction context
        context = {
            "language": instance.language,
            "instance_id": instance.instance_id,
            "build_files": ", ".join(instance.build_files),
            "env_specs": json.dumps(instance.env_specs, indent=2),
        }

        return self._render_template(template_path, context)

    def _prepare_task_from_template(
        self, instance: DIBenchInstance, output_dir: Path
    ) -> None:
        """Prepare a DI-Bench task directory in Harbor structure."""
        # Clean and create output directory
        shutil.rmtree(output_dir, ignore_errors=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize TaskPaths for Harbor structure
        task_paths = TaskPaths(task_dir=output_dir)

        # Create directory structure
        task_paths.solution_dir.mkdir(parents=True, exist_ok=True)
        task_paths.tests_dir.mkdir(parents=True, exist_ok=True)
        task_paths.environment_dir.mkdir(parents=True, exist_ok=True)

        # Get repository path
        repo_path = self._get_repo_path(instance.language, instance.instance_id)

        # 1. Write instruction.md
        instruction = self._create_instruction(instance, repo_path)
        task_paths.instruction_path.write_text(instruction)

        # 2. Create task.toml
        task_toml_template = self.templates_dir / "task.toml"
        if task_toml_template.exists():
            template_content = task_toml_template.read_text()
            task_config = TaskConfig.model_validate_toml(template_content)

            # Update metadata
            task_config.metadata["language"] = instance.language
            task_config.metadata["instance_id"] = instance.instance_id
            task_config.metadata["tags"] = [
                "dibench",
                instance.language.lower(),
                "dependency-inference",
            ]

            task_paths.config_path.write_text(task_config.model_dump_toml())
        else:
            raise FileNotFoundError(f"Template {task_toml_template} not found")

        # 3. Copy repository to environment/repo
        env_repo_dir = task_paths.environment_dir / "repo"
        if repo_path.exists():
            shutil.copytree(repo_path, env_repo_dir, symlinks=True)

        # 4. Generate environment/Dockerfile
        dockerfile_template = self.templates_dir / "environment" / "Dockerfile"
        if dockerfile_template.exists():
            dockerfile_content = self._render_template(
                dockerfile_template,
                {
                    "language": instance.language.lower(),
                    "env_specs": json.dumps(instance.env_specs),
                }
            )
            (task_paths.environment_dir / "Dockerfile").write_text(dockerfile_content)
        else:
            raise FileNotFoundError(f"Template {dockerfile_template} not found")

        # 5. Generate solution/solve.sh with reference patch
        solve_template = self.templates_dir / "solution" / "solve.sh"
        if solve_template.exists():
            solve_content = self._render_template(
                solve_template,
                {"patch": instance.patch if instance.patch else "# No reference patch available"}
            )
            task_paths.solve_path.write_text(solve_content)
            task_paths.solve_path.chmod(0o755)
        else:
            raise FileNotFoundError(f"Template {solve_template} not found")

        # 6. Generate tests/test.sh
        test_template = self.templates_dir / "tests" / "test.sh"
        if test_template.exists():
            test_content = self._render_template(
                test_template,
                {
                    "act_command": instance.act_command,
                    "ci_file": instance.ci_file,
                }
            )
            task_paths.test_path.write_text(test_content)
            task_paths.test_path.chmod(0o755)
        else:
            raise FileNotFoundError(f"Template {test_template} not found")

        # 7. Save instance metadata
        metadata_path = task_paths.tests_dir / "instance.json"
        with open(metadata_path, "w") as f:
            json.dump({
                "instance_id": instance.instance_id,
                "language": instance.language,
                "metadata": instance.metadata,
                "build_files": instance.build_files,
                "env_specs": instance.env_specs,
                "act_command": instance.act_command,
                "ci_file": instance.ci_file,
            }, f, indent=2)

    def generate_task(self, task_id: str, local_task_id: str) -> None:
        """
        Generate a new Harbor task for a DI-Bench instance.

        Args:
            task_id: DI-Bench task ID (format: "language/instance_id")
            local_task_id: Local directory name for the task
        """
        instance = self.loader.load(task_id)
        out_dir = self.task_dir / local_task_id
        out_dir.mkdir(parents=True, exist_ok=True)

        self._prepare_task_from_template(instance, out_dir)
