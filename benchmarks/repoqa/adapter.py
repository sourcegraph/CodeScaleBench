"""
RepoQA Adapter for Harbor

Converts RepoQA instances into Harbor task structure with three variants:
- SR-QA: Semantic Retrieval (find function by description)
- MD-QA: Multi-Hop Dependency (find call path)
- NR-QA: Negative/Disambiguation (pick correct function among similar ones)
"""

import json
import shutil
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Dict, List, Optional

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

ADAPTER_NAME = "repoqa"
TEMPLATE_DIR = Path(__file__).parent / "templates"


@dataclass
class RepoQAInstance:
    """Represents a single RepoQA instance."""
    instance_id: str
    repository: str          # e.g., "pytorch/pytorch"
    commit: str              # Repository commit hash
    language: str            # python, javascript, rust, etc.
    function_description: str
    canonical_function: str  # "path/to/file.py::function_name"
    canonical_path: str
    canonical_name: str
    semantic_metadata: Dict[str, bool]  # mutates_state, throws_errors, etc.
    
    @classmethod
    def from_dict(cls, data: dict) -> "RepoQAInstance":
        """Create instance from dictionary."""
        return cls(
            instance_id=data["instance_id"],
            repository=data["repository"],
            commit=data["commit"],
            language=data["language"],
            function_description=data["function_description"],
            canonical_function=data["canonical_function"],
            canonical_path=data["canonical_path"],
            canonical_name=data["canonical_name"],
            semantic_metadata=data.get("semantic_metadata", {}),
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
        task_variant: str,
    ) -> None:
        raise NotImplementedError("Adapter must implement this method.")


class RepoQALoader:
    """Loads RepoQA instances from dataset file."""

    def __init__(self, dataset_path: Optional[Path] = None):
        """
        Initialize the loader.

        Args:
            dataset_path: Path to JSONL dataset file.
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
                instance = RepoQAInstance.from_dict(data)
                self._instances[instance.instance_id] = instance

    def load(self, instance_id: str) -> RepoQAInstance:
        """Load a single instance by ID."""
        if instance_id in self._instances:
            return self._instances[instance_id]
        raise KeyError(f"Instance not found: {instance_id}")

    def all_ids(self) -> List[str]:
        """Return all instance IDs."""
        return sorted(self._instances.keys())


class RepoQAAdapter(BaseAdapter):
    """Adapter that converts RepoQA tasks into Harbor task directories."""

    NAME = "repoqa"

    def __init__(
        self,
        task_dir: Path,
        dataset_path: Optional[Path] = None,
        **kwargs
    ):
        """
        Initialize RepoQA adapter.

        Args:
            task_dir: Output directory for Harbor tasks
            dataset_path: Path to JSONL dataset file
            **kwargs: Additional arguments
        """
        super().__init__(**kwargs)
        self.task_dir = Path(task_dir)
        self.loader = RepoQALoader(dataset_path)
        self.templates_dir = TEMPLATE_DIR

    def _render_template(self, template_path: Path, context: dict) -> str:
        """Simple template rendering by replacing {key} placeholders."""
        content = template_path.read_text()
        for key, value in context.items():
            content = content.replace(f"{{{key}}}", str(value))
            content = content.replace(f"{{{{ {key} }}}}", str(value))
        return content

    def _create_instruction(
        self,
        instance: RepoQAInstance,
        task_variant: str,
    ) -> str:
        """Create instruction.md content for the task variant."""
        template_path = self.templates_dir / f"instruction_{task_variant}.md"

        if not template_path.exists():
            # Fallback to generic instruction
            template_path = self.templates_dir / "instruction.md"

        context = {
            "function_description": instance.function_description,
            "language": instance.language,
            "repository": instance.repository,
            "commit": instance.commit,
            "semantic_constraint": json.dumps(instance.semantic_metadata),
        }

        return self._render_template(template_path, context)

    def _prepare_task_from_template(
        self,
        instance: RepoQAInstance,
        task_variant: str,
        output_dir: Path,
    ) -> None:
        """Prepare a RepoQA task directory in Harbor structure."""
        # Clean and create output directory
        shutil.rmtree(output_dir, ignore_errors=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize TaskPaths for Harbor structure
        task_paths = TaskPaths(task_dir=output_dir)

        # Create directory structure
        task_paths.solution_dir.mkdir(parents=True, exist_ok=True)
        task_paths.tests_dir.mkdir(parents=True, exist_ok=True)
        task_paths.environment_dir.mkdir(parents=True, exist_ok=True)

        # 1. Write instruction.md
        instruction = self._create_instruction(instance, task_variant)
        task_paths.instruction_path.write_text(instruction)

        # 2. Create task.toml
        task_toml_template = self.templates_dir / "task.toml"
        if task_toml_template.exists():
            template_content = task_toml_template.read_text()
            task_config = TaskConfig.model_validate_toml(template_content)

            # Update metadata
            task_config.metadata["repository"] = instance.repository
            task_config.metadata["commit"] = instance.commit
            task_config.metadata["language"] = instance.language
            task_config.metadata["task_variant"] = task_variant
            task_config.metadata["tags"] = [
                "repoqa",
                instance.language.lower(),
                f"repoqa-{task_variant}",
            ]

            task_paths.config_path.write_text(task_config.model_dump_toml())
        else:
            raise FileNotFoundError(f"Template {task_toml_template} not found")

        # 3. Generate environment/Dockerfile
        dockerfile_template = self.templates_dir / "environment" / "Dockerfile"
        if dockerfile_template.exists():
            dockerfile_content = self._render_template(
                dockerfile_template,
                {
                    "repository": instance.repository,
                    "commit": instance.commit,
                }
            )
            (task_paths.environment_dir / "Dockerfile").write_text(dockerfile_content)
        else:
            raise FileNotFoundError(f"Template {dockerfile_template} not found")

        # 4. Save ground truth (canonical function metadata)
        ground_truth = {
            "function_id": instance.canonical_function,
            "canonical_path": instance.canonical_path,
            "canonical_name": instance.canonical_name,
            "language": instance.language,
            "nl_description": instance.function_description,
            "task_variant": task_variant,
            **instance.semantic_metadata,
        }
        ground_truth_path = task_paths.tests_dir / "ground_truth.json"
        with open(ground_truth_path, "w") as f:
            json.dump(ground_truth, f, indent=2)

        # 5. Generate tests/test.sh
        test_template = self.templates_dir / "tests" / "test.sh"
        if test_template.exists():
            test_content = self._render_template(
                test_template,
                {
                    "task_variant": task_variant,
                }
            )
            task_paths.test_path.write_text(test_content)
            task_paths.test_path.chmod(0o755)
        else:
            raise FileNotFoundError(f"Template {test_template} not found")

        # 6. Save instance metadata
        metadata_path = task_paths.tests_dir / "instance.json"
        with open(metadata_path, "w") as f:
            json.dump({
                "instance_id": instance.instance_id,
                "repository": instance.repository,
                "commit": instance.commit,
                "language": instance.language,
                "task_variant": task_variant,
                "canonical_function": instance.canonical_function,
            }, f, indent=2)
        
        # 7. Copy verifier.py template to tests directory (where test.sh can find it)
        verifier_template = self.templates_dir / "verifier.py"
        if verifier_template.exists():
            verifier_content = verifier_template.read_text()
            # Copy to tests/ so it's available when test.sh runs
            verifier_path = task_paths.tests_dir / "verifier.py"
            verifier_path.write_text(verifier_content)
            verifier_path.chmod(0o755)
        else:
            raise FileNotFoundError(f"Template {verifier_template} not found")
        
        # 8. Copy verifiers.py module to tests directory (required for imports)
        verifiers_module = Path(__file__).parent / "verifiers.py"
        if verifiers_module.exists():
            verifiers_content = verifiers_module.read_text()
            verifiers_path = task_paths.tests_dir / "verifiers.py"
            verifiers_path.write_text(verifiers_content)
        else:
            raise FileNotFoundError(f"Verifiers module {verifiers_module} not found")

    def generate_task(
        self,
        task_id: str,
        local_task_id: str,
        task_variant: str = "sr-qa",
    ) -> None:
        """
        Generate a new Harbor task for a RepoQA instance.

        Args:
            task_id: RepoQA instance ID
            local_task_id: Local directory name for the task
            task_variant: "sr-qa", "md-qa", or "nr-qa"
        """
        instance = self.loader.load(task_id)
        out_dir = self.task_dir / local_task_id
        out_dir.mkdir(parents=True, exist_ok=True)

        self._prepare_task_from_template(instance, task_variant, out_dir)
