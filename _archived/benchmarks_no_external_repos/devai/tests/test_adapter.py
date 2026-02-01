"""
Tests for DevAI data model and loader.
"""

import json
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from benchmarks.devai.adapter import (
    DEVAI_DOMAINS,
    DevAIAdapter,
    DevAILoader,
    DevAITask,
    Preference,
    Requirement,
)


class TestRequirement:
    """Tests for the Requirement dataclass."""

    def test_requirement_creation(self) -> None:
        """Test creating a requirement with default values."""
        req = Requirement(
            id="R1",
            description="The application must handle user authentication",
        )
        assert req.id == "R1"
        assert req.description == "The application must handle user authentication"
        assert req.dependencies == []
        assert req.priority == 1
        assert req.category == "functional"

    def test_requirement_with_dependencies(self) -> None:
        """Test creating a requirement with dependencies."""
        req = Requirement(
            id="R1.1",
            description="Support OAuth2 authentication",
            dependencies=["R1"],
            priority=2,
            category="functional",
        )
        assert req.id == "R1.1"
        assert req.dependencies == ["R1"]
        assert req.priority == 2

    def test_requirement_to_dict(self) -> None:
        """Test converting requirement to dictionary."""
        req = Requirement(
            id="R2",
            description="API must return JSON",
            dependencies=["R1"],
            priority=1,
            category="non-functional",
        )
        result = req.to_dict()
        assert result["id"] == "R2"
        assert result["description"] == "API must return JSON"
        assert result["dependencies"] == ["R1"]
        assert result["priority"] == 1
        assert result["category"] == "non-functional"

    def test_requirement_from_dict(self) -> None:
        """Test creating requirement from dictionary."""
        data = {
            "id": "R3",
            "description": "Handle concurrent requests",
            "dependencies": ["R1", "R2"],
            "priority": 2,
            "category": "constraint",
        }
        req = Requirement.from_dict(data)
        assert req.id == "R3"
        assert req.description == "Handle concurrent requests"
        assert req.dependencies == ["R1", "R2"]
        assert req.priority == 2
        assert req.category == "constraint"

    def test_requirement_from_dict_with_defaults(self) -> None:
        """Test requirement from_dict uses defaults for missing fields."""
        data = {"id": "R4", "description": "Basic requirement"}
        req = Requirement.from_dict(data)
        assert req.id == "R4"
        assert req.dependencies == []
        assert req.priority == 1
        assert req.category == "functional"


class TestPreference:
    """Tests for the Preference dataclass."""

    def test_preference_creation(self) -> None:
        """Test creating a preference."""
        pref = Preference(
            name="language",
            value="Python",
            rationale="Team expertise",
        )
        assert pref.name == "language"
        assert pref.value == "Python"
        assert pref.rationale == "Team expertise"

    def test_preference_with_empty_rationale(self) -> None:
        """Test creating a preference without rationale."""
        pref = Preference(name="framework", value="FastAPI")
        assert pref.name == "framework"
        assert pref.value == "FastAPI"
        assert pref.rationale == ""

    def test_preference_to_dict(self) -> None:
        """Test converting preference to dictionary."""
        pref = Preference(
            name="database",
            value="PostgreSQL",
            rationale="ACID compliance",
        )
        result = pref.to_dict()
        assert result["name"] == "database"
        assert result["value"] == "PostgreSQL"
        assert result["rationale"] == "ACID compliance"

    def test_preference_from_dict(self) -> None:
        """Test creating preference from dictionary."""
        data = {
            "name": "testing",
            "value": "pytest",
            "rationale": "Standard library",
        }
        pref = Preference.from_dict(data)
        assert pref.name == "testing"
        assert pref.value == "pytest"
        assert pref.rationale == "Standard library"


class TestDevAITask:
    """Tests for the DevAITask dataclass."""

    def test_task_creation_minimal(self) -> None:
        """Test creating a task with minimal fields."""
        task = DevAITask(
            id="devai-001",
            user_query="Build a REST API for managing todos",
        )
        assert task.id == "devai-001"
        assert task.user_query == "Build a REST API for managing todos"
        assert task.requirements == []
        assert task.preferences == []
        assert task.domain == "general"

    def test_task_creation_full(self) -> None:
        """Test creating a task with all fields."""
        requirements = [
            Requirement(id="R1", description="Create endpoints"),
            Requirement(id="R1.1", description="GET /todos", dependencies=["R1"]),
        ]
        preferences = [
            Preference(name="framework", value="FastAPI"),
        ]

        task = DevAITask(
            id="devai-002",
            user_query="Build a web scraper",
            requirements=requirements,
            preferences=preferences,
            domain="automation",
            description="Extended description here",
            metadata={"difficulty": "medium"},
        )

        assert task.id == "devai-002"
        assert len(task.requirements) == 2
        assert len(task.preferences) == 1
        assert task.domain == "automation"
        assert task.metadata["difficulty"] == "medium"

    def test_task_domain_normalization(self) -> None:
        """Test that domain is normalized to lowercase."""
        task = DevAITask(
            id="devai-003",
            user_query="Test query",
            domain="WEB",
        )
        assert task.domain == "web"

    def test_task_to_dict(self) -> None:
        """Test converting task to dictionary."""
        task = DevAITask(
            id="devai-004",
            user_query="Create CLI tool",
            requirements=[Requirement(id="R1", description="Parse args")],
            preferences=[Preference(name="cli_lib", value="click")],
            domain="cli",
        )
        result = task.to_dict()

        assert result["id"] == "devai-004"
        assert result["user_query"] == "Create CLI tool"
        assert len(result["requirements"]) == 1
        assert result["requirements"][0]["id"] == "R1"
        assert len(result["preferences"]) == 1
        assert result["domain"] == "cli"

    def test_task_from_dict(self) -> None:
        """Test creating task from dictionary."""
        data = {
            "id": "devai-005",
            "user_query": "Build data pipeline",
            "requirements": [
                {"id": "R1", "description": "Read CSV files"},
                {"id": "R2", "description": "Transform data", "dependencies": ["R1"]},
            ],
            "preferences": [
                {"name": "library", "value": "pandas"},
            ],
            "domain": "data",
            "metadata": {"tags": ["etl", "csv"]},
        }
        task = DevAITask.from_dict(data)

        assert task.id == "devai-005"
        assert task.user_query == "Build data pipeline"
        assert len(task.requirements) == 2
        assert task.requirements[1].dependencies == ["R1"]
        assert len(task.preferences) == 1
        assert task.domain == "data"
        assert task.metadata["tags"] == ["etl", "csv"]

    def test_task_get_root_requirements(self) -> None:
        """Test getting root requirements (no dependencies)."""
        task = DevAITask(
            id="devai-006",
            user_query="Test task",
            requirements=[
                Requirement(id="R1", description="Root 1"),
                Requirement(id="R2", description="Root 2"),
                Requirement(id="R1.1", description="Child 1", dependencies=["R1"]),
                Requirement(id="R2.1", description="Child 2", dependencies=["R2"]),
            ],
        )
        roots = task.get_root_requirements()
        assert len(roots) == 2
        root_ids = [r.id for r in roots]
        assert "R1" in root_ids
        assert "R2" in root_ids

    def test_task_get_dependent_requirements(self) -> None:
        """Test getting requirements that depend on a given requirement."""
        task = DevAITask(
            id="devai-007",
            user_query="Test task",
            requirements=[
                Requirement(id="R1", description="Root"),
                Requirement(id="R1.1", description="Child 1", dependencies=["R1"]),
                Requirement(id="R1.2", description="Child 2", dependencies=["R1"]),
                Requirement(id="R2", description="Independent"),
            ],
        )
        dependents = task.get_dependent_requirements("R1")
        assert len(dependents) == 2
        dep_ids = [r.id for r in dependents]
        assert "R1.1" in dep_ids
        assert "R1.2" in dep_ids

    def test_task_get_requirement_count(self) -> None:
        """Test getting requirement count."""
        task = DevAITask(
            id="devai-008",
            user_query="Test task",
            requirements=[
                Requirement(id="R1", description="Req 1"),
                Requirement(id="R2", description="Req 2"),
                Requirement(id="R3", description="Req 3"),
            ],
        )
        assert task.get_requirement_count() == 3


class TestDevAILoader:
    """Tests for the DevAILoader class."""

    @pytest.fixture
    def temp_data_dir(self) -> Generator[Path, None, None]:
        """Create a temporary data directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_loader_initialization_default(self) -> None:
        """Test loader initializes with default data directory."""
        loader = DevAILoader()
        assert loader.data_dir == Path(__file__).parent.parent / "data"
        assert not loader._loaded

    def test_loader_initialization_custom_path(self, temp_data_dir: Path) -> None:
        """Test loader initializes with custom data directory."""
        loader = DevAILoader(data_dir=temp_data_dir)
        assert loader.data_dir == temp_data_dir

    def test_loader_load_empty_directory(self, temp_data_dir: Path) -> None:
        """Test loader returns empty list for empty directory."""
        loader = DevAILoader(data_dir=temp_data_dir)
        tasks = loader.load()
        assert tasks == []
        assert loader._loaded

    def test_loader_load_individual_files(self, temp_data_dir: Path) -> None:
        """Test loading tasks from individual JSON files."""
        # Create test task files
        task1 = {
            "id": "devai-001",
            "user_query": "Build a CLI",
            "domain": "cli",
            "requirements": [{"id": "R1", "description": "Parse args"}],
        }
        task2 = {
            "id": "devai-002",
            "user_query": "Create API",
            "domain": "web",
            "requirements": [{"id": "R1", "description": "Handle requests"}],
        }

        (temp_data_dir / "devai-001.json").write_text(json.dumps(task1))
        (temp_data_dir / "devai-002.json").write_text(json.dumps(task2))

        loader = DevAILoader(data_dir=temp_data_dir)
        tasks = loader.load()

        assert len(tasks) == 2
        task_ids = [t.id for t in tasks]
        assert "devai-001" in task_ids
        assert "devai-002" in task_ids

    def test_loader_load_combined_file(self, temp_data_dir: Path) -> None:
        """Test loading tasks from combined tasks.json file."""
        tasks_data = [
            {"id": "devai-001", "user_query": "Task 1", "domain": "web"},
            {"id": "devai-002", "user_query": "Task 2", "domain": "cli"},
            {"id": "devai-003", "user_query": "Task 3", "domain": "data"},
        ]

        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = DevAILoader(data_dir=temp_data_dir)
        tasks = loader.load()

        assert len(tasks) == 3

    def test_loader_load_combined_file_with_tasks_key(self, temp_data_dir: Path) -> None:
        """Test loading from combined file with 'tasks' key."""
        data = {
            "version": "1.0",
            "tasks": [
                {"id": "devai-001", "user_query": "Task 1", "domain": "web"},
                {"id": "devai-002", "user_query": "Task 2", "domain": "cli"},
            ],
        }

        (temp_data_dir / "tasks.json").write_text(json.dumps(data))

        loader = DevAILoader(data_dir=temp_data_dir)
        tasks = loader.load()

        assert len(tasks) == 2

    def test_loader_load_from_manifest(self, temp_data_dir: Path) -> None:
        """Test loading tasks from manifest file."""
        tasks_subdir = temp_data_dir / "tasks"
        tasks_subdir.mkdir()

        # Create task files
        task1 = {"id": "devai-001", "user_query": "Task 1", "domain": "web"}
        task2 = {"id": "devai-002", "user_query": "Task 2", "domain": "api"}
        (tasks_subdir / "devai-001.json").write_text(json.dumps(task1))
        (tasks_subdir / "devai-002.json").write_text(json.dumps(task2))

        # Create manifest
        manifest = {"tasks": ["devai-001.json", "devai-002.json"]}
        (temp_data_dir / "manifest.json").write_text(json.dumps(manifest))

        loader = DevAILoader(data_dir=temp_data_dir)
        tasks = loader.load()

        assert len(tasks) == 2

    def test_loader_all_ids(self, temp_data_dir: Path) -> None:
        """Test getting all task IDs."""
        tasks_data = [
            {"id": "devai-001", "user_query": "Task 1"},
            {"id": "devai-002", "user_query": "Task 2"},
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = DevAILoader(data_dir=temp_data_dir)
        ids = loader.all_ids()

        assert len(ids) == 2
        assert "devai-001" in ids
        assert "devai-002" in ids

    def test_loader_filter_by_domain(self, temp_data_dir: Path) -> None:
        """Test filtering tasks by domain."""
        tasks_data = [
            {"id": "devai-001", "user_query": "Task 1", "domain": "web"},
            {"id": "devai-002", "user_query": "Task 2", "domain": "web"},
            {"id": "devai-003", "user_query": "Task 3", "domain": "cli"},
            {"id": "devai-004", "user_query": "Task 4", "domain": "data"},
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = DevAILoader(data_dir=temp_data_dir)
        web_tasks = loader.filter_by_domain("web")

        assert len(web_tasks) == 2
        for task in web_tasks:
            assert task.domain == "web"

    def test_loader_filter_by_domain_case_insensitive(self, temp_data_dir: Path) -> None:
        """Test that domain filtering is case-insensitive."""
        tasks_data = [
            {"id": "devai-001", "user_query": "Task 1", "domain": "WEB"},
            {"id": "devai-002", "user_query": "Task 2", "domain": "web"},
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = DevAILoader(data_dir=temp_data_dir)
        # Both should be normalized to lowercase
        web_tasks = loader.filter_by_domain("WEB")

        assert len(web_tasks) == 2

    def test_loader_get_task(self, temp_data_dir: Path) -> None:
        """Test getting a specific task by ID."""
        tasks_data = [
            {"id": "devai-001", "user_query": "Task 1", "domain": "web"},
            {"id": "devai-002", "user_query": "Task 2", "domain": "cli"},
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = DevAILoader(data_dir=temp_data_dir)
        task = loader.get_task("devai-002")

        assert task is not None
        assert task.id == "devai-002"
        assert task.domain == "cli"

    def test_loader_get_task_not_found(self, temp_data_dir: Path) -> None:
        """Test getting a non-existent task returns None."""
        tasks_data = [{"id": "devai-001", "user_query": "Task 1"}]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = DevAILoader(data_dir=temp_data_dir)
        task = loader.get_task("devai-999")

        assert task is None

    def test_loader_get_domains(self, temp_data_dir: Path) -> None:
        """Test getting list of unique domains."""
        tasks_data = [
            {"id": "devai-001", "user_query": "Task 1", "domain": "web"},
            {"id": "devai-002", "user_query": "Task 2", "domain": "cli"},
            {"id": "devai-003", "user_query": "Task 3", "domain": "web"},
            {"id": "devai-004", "user_query": "Task 4", "domain": "data"},
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = DevAILoader(data_dir=temp_data_dir)
        domains = loader.get_domains()

        assert len(domains) == 3
        assert "web" in domains
        assert "cli" in domains
        assert "data" in domains

    def test_loader_task_count(self, temp_data_dir: Path) -> None:
        """Test getting total task count."""
        tasks_data = [
            {"id": "devai-001", "user_query": "Task 1"},
            {"id": "devai-002", "user_query": "Task 2"},
            {"id": "devai-003", "user_query": "Task 3"},
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = DevAILoader(data_dir=temp_data_dir)
        assert loader.task_count() == 3

    def test_loader_total_requirement_count(self, temp_data_dir: Path) -> None:
        """Test getting total requirement count across all tasks."""
        tasks_data = [
            {
                "id": "devai-001",
                "user_query": "Task 1",
                "requirements": [
                    {"id": "R1", "description": "Req 1"},
                    {"id": "R2", "description": "Req 2"},
                ],
            },
            {
                "id": "devai-002",
                "user_query": "Task 2",
                "requirements": [
                    {"id": "R1", "description": "Req 1"},
                    {"id": "R2", "description": "Req 2"},
                    {"id": "R3", "description": "Req 3"},
                ],
            },
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = DevAILoader(data_dir=temp_data_dir)
        total_reqs = loader.total_requirement_count()

        assert total_reqs == 5

    def test_loader_filter_by_requirement_count(self, temp_data_dir: Path) -> None:
        """Test filtering tasks by requirement count."""
        tasks_data = [
            {
                "id": "devai-001",
                "user_query": "Task 1",
                "requirements": [{"id": "R1", "description": "Req 1"}],
            },
            {
                "id": "devai-002",
                "user_query": "Task 2",
                "requirements": [
                    {"id": "R1", "description": "Req 1"},
                    {"id": "R2", "description": "Req 2"},
                    {"id": "R3", "description": "Req 3"},
                ],
            },
            {
                "id": "devai-003",
                "user_query": "Task 3",
                "requirements": [
                    {"id": "R1", "description": "Req 1"},
                    {"id": "R2", "description": "Req 2"},
                ],
            },
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = DevAILoader(data_dir=temp_data_dir)

        # Filter for tasks with at least 2 requirements
        filtered = loader.filter_by_requirement_count(min_requirements=2)
        assert len(filtered) == 2

        # Filter for tasks with at most 2 requirements
        filtered = loader.filter_by_requirement_count(max_requirements=2)
        assert len(filtered) == 2

        # Filter for tasks with exactly 2-3 requirements
        filtered = loader.filter_by_requirement_count(min_requirements=2, max_requirements=3)
        assert len(filtered) == 2

    def test_loader_caches_loaded_tasks(self, temp_data_dir: Path) -> None:
        """Test that loader caches tasks and doesn't reload."""
        tasks_data = [{"id": "devai-001", "user_query": "Task 1"}]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = DevAILoader(data_dir=temp_data_dir)
        tasks1 = loader.load()
        tasks2 = loader.load()

        # Should be the same list object (cached)
        assert tasks1 is tasks2

    def test_loader_handles_malformed_json(self, temp_data_dir: Path) -> None:
        """Test that loader handles malformed JSON gracefully."""
        # Write valid tasks.json
        tasks_data = [{"id": "devai-001", "user_query": "Task 1"}]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        # Write malformed individual file (shouldn't crash loading)
        (temp_data_dir / "bad.json").write_text("{invalid json")

        loader = DevAILoader(data_dir=temp_data_dir)
        tasks = loader.load()

        # Should load the valid task from tasks.json
        assert len(tasks) == 1

    def test_loader_generates_id_from_filename(self, temp_data_dir: Path) -> None:
        """Test that loader generates task ID from filename when not in data."""
        task_data = {"user_query": "Task without ID"}
        (temp_data_dir / "my-task.json").write_text(json.dumps(task_data))

        loader = DevAILoader(data_dir=temp_data_dir)
        tasks = loader.load()

        assert len(tasks) == 1
        assert tasks[0].id == "my-task"


class TestDevAIDomains:
    """Tests for DevAI domain constants."""

    def test_domains_defined(self) -> None:
        """Test that expected domains are defined."""
        assert "web" in DEVAI_DOMAINS
        assert "cli" in DEVAI_DOMAINS
        assert "data" in DEVAI_DOMAINS
        assert "automation" in DEVAI_DOMAINS
        assert "api" in DEVAI_DOMAINS

    def test_domains_are_lowercase(self) -> None:
        """Test that all domains are lowercase."""
        for domain in DEVAI_DOMAINS:
            assert domain == domain.lower()


class TestDevAIAdapter:
    """Tests for DevAIAdapter class."""

    @pytest.fixture
    def temp_output_dir(self) -> Generator[Path, None, None]:
        """Create a temporary output directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def temp_data_dir(self) -> Generator[Path, None, None]:
        """Create a temporary data directory with test tasks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)

            # Create sample task
            task_data = {
                "id": "devai-web-001",
                "user_query": "Build a REST API for a todo application",
                "domain": "web",
                "description": "Create a simple CRUD API for managing todos",
                "requirements": [
                    {"id": "R1", "description": "Create GET /todos endpoint", "priority": 1},
                    {"id": "R2", "description": "Create POST /todos endpoint", "priority": 1, "dependencies": ["R1"]},
                    {"id": "R3", "description": "Create DELETE /todos endpoint", "priority": 2, "dependencies": ["R1"]},
                ],
                "preferences": [
                    {"name": "framework", "value": "FastAPI", "rationale": "Modern async framework"},
                ],
                "metadata": {"difficulty": "easy"},
            }
            (data_dir / "tasks.json").write_text(json.dumps([task_data]))

            yield data_dir

    def test_adapter_initialization(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test adapter initializes correctly."""
        adapter = DevAIAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )
        assert adapter.task_dir == temp_output_dir
        assert adapter.loader is not None
        assert adapter.templates_dir.exists()

    def test_generate_task_creates_directory_structure(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test generate_task creates correct directory structure."""
        adapter = DevAIAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )
        out_dir = adapter.generate_task("devai-web-001")

        # Check directory structure
        assert out_dir.exists()
        assert (out_dir / "instruction.md").exists()
        assert (out_dir / "task.toml").exists()
        assert (out_dir / "environment").is_dir()
        assert (out_dir / "environment" / "Dockerfile").exists()
        assert (out_dir / "environment" / "project").is_dir()
        assert (out_dir / "tests").is_dir()
        assert (out_dir / "tests" / "test.sh").exists()
        assert (out_dir / "tests" / "verify.py").exists()
        assert (out_dir / "tests" / "ground_truth.json").exists()
        assert (out_dir / "tests" / "trajectory-schema.json").exists()

    def test_generate_task_with_local_task_id(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test generate_task uses local_task_id for directory name."""
        adapter = DevAIAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )
        out_dir = adapter.generate_task("devai-web-001", "my-custom-name")

        assert out_dir.name == "my-custom-name"
        assert out_dir.exists()

    def test_generate_task_instruction_md_content(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test generated instruction.md contains task information."""
        adapter = DevAIAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )
        out_dir = adapter.generate_task("devai-web-001")

        instruction_content = (out_dir / "instruction.md").read_text()

        # Check content contains expected information
        assert "devai-web-001" in instruction_content
        assert "web" in instruction_content
        assert "REST API" in instruction_content
        assert "todo" in instruction_content.lower()
        # Check requirements are included
        assert "R1" in instruction_content
        assert "GET /todos" in instruction_content
        # Check preferences are included
        assert "FastAPI" in instruction_content

    def test_generate_task_task_toml_content(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test generated task.toml contains correct metadata."""
        adapter = DevAIAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )
        out_dir = adapter.generate_task("devai-web-001")

        task_toml_content = (out_dir / "task.toml").read_text()

        # Check content contains expected information
        assert "devai-web-001" in task_toml_content
        assert "devai" in task_toml_content
        assert "web" in task_toml_content
        assert "requirement_count = 3" in task_toml_content

    def test_generate_task_dockerfile_uses_python_and_uv(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test Dockerfile uses Python 3.10+ and uv package manager."""
        adapter = DevAIAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )
        out_dir = adapter.generate_task("devai-web-001")

        dockerfile_content = (out_dir / "environment" / "Dockerfile").read_text()

        # Check Dockerfile content
        assert "python:3.10" in dockerfile_content
        assert "uv" in dockerfile_content
        assert "astral.sh/uv" in dockerfile_content
        assert "/trajectory" in dockerfile_content
        assert "/workspace" in dockerfile_content

    def test_generate_task_ground_truth_json(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test generated ground_truth.json contains task data."""
        adapter = DevAIAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )
        out_dir = adapter.generate_task("devai-web-001")

        ground_truth_path = out_dir / "tests" / "ground_truth.json"
        with open(ground_truth_path) as f:
            ground_truth = json.load(f)

        assert ground_truth["task_id"] == "devai-web-001"
        assert ground_truth["domain"] == "web"
        assert "REST API" in ground_truth["user_query"]
        assert len(ground_truth["requirements"]) == 3
        assert len(ground_truth["preferences"]) == 1
        # Check requirements have correct structure
        req_ids = [r["id"] for r in ground_truth["requirements"]]
        assert "R1" in req_ids
        assert "R2" in req_ids
        assert "R3" in req_ids

    def test_generate_task_trajectory_schema_json(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test generated trajectory-schema.json is valid."""
        adapter = DevAIAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )
        out_dir = adapter.generate_task("devai-web-001")

        schema_path = out_dir / "tests" / "trajectory-schema.json"
        with open(schema_path) as f:
            schema = json.load(f)

        # Check schema has required fields
        assert "$schema" in schema
        assert "properties" in schema
        assert "required" in schema
        assert "task_id" in schema["required"]
        assert "steps" in schema["required"]
        assert "final_state" in schema["required"]

    def test_generate_task_test_sh_is_executable(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test generated test.sh has executable permissions."""
        import os

        adapter = DevAIAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )
        out_dir = adapter.generate_task("devai-web-001")

        test_sh_path = out_dir / "tests" / "test.sh"
        assert os.access(test_sh_path, os.X_OK)

    def test_generate_task_verify_py_is_executable(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test generated verify.py has executable permissions."""
        import os

        adapter = DevAIAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )
        out_dir = adapter.generate_task("devai-web-001")

        verify_py_path = out_dir / "tests" / "verify.py"
        assert os.access(verify_py_path, os.X_OK)

    def test_generate_task_nonexistent_raises_error(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test generate_task raises error for nonexistent task."""
        adapter = DevAIAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )

        with pytest.raises(ValueError, match="Task not found"):
            adapter.generate_task("nonexistent-task-id")

    def test_render_template_replaces_placeholders(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test _render_template correctly replaces placeholders."""
        adapter = DevAIAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )

        # Create a simple template file
        template_dir = temp_output_dir / "templates"
        template_dir.mkdir()
        template_file = template_dir / "test.txt"
        template_file.write_text("Task: {id}, Domain: {domain}")

        result = adapter._render_template(
            template_file,
            {"id": "test-001", "domain": "web"},
        )

        assert result == "Task: test-001, Domain: web"

    def test_generate_dockerfile_content(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test _generate_dockerfile returns valid Dockerfile content."""
        adapter = DevAIAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )

        dockerfile = adapter._generate_dockerfile()

        # Check essential components
        assert "FROM python:3.10" in dockerfile
        assert "apt-get" in dockerfile
        assert "uv" in dockerfile
        assert "/workspace" in dockerfile
        assert "/trajectory" in dockerfile
        assert "CMD" in dockerfile

    def test_format_requirements_markdown(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test _format_requirements_markdown generates proper markdown."""
        adapter = DevAIAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )

        requirements = [
            Requirement(id="R1", description="First req", priority=1),
            Requirement(id="R2", description="Second req", priority=2, dependencies=["R1"]),
        ]

        result = adapter._format_requirements_markdown(requirements)

        assert "### Requirements" in result
        assert "R1" in result
        assert "R2" in result
        assert "First req" in result
        assert "Depends on" in result  # Dependency indicator

    def test_format_requirements_markdown_empty(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test _format_requirements_markdown returns empty for empty list."""
        adapter = DevAIAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )

        result = adapter._format_requirements_markdown([])
        assert result == ""

    def test_format_preferences_markdown(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test _format_preferences_markdown generates proper markdown."""
        adapter = DevAIAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )

        preferences = [
            Preference(name="framework", value="FastAPI", rationale="Fast and modern"),
            Preference(name="db", value="PostgreSQL"),
        ]

        result = adapter._format_preferences_markdown(preferences)

        assert "### Preferences" in result
        assert "framework" in result
        assert "FastAPI" in result
        assert "Rationale" in result
        assert "db" in result
        assert "PostgreSQL" in result

    def test_format_preferences_markdown_empty(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test _format_preferences_markdown returns empty for empty list."""
        adapter = DevAIAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )

        result = adapter._format_preferences_markdown([])
        assert result == ""

    def test_create_trajectory_schema(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test _create_trajectory_schema returns valid schema."""
        adapter = DevAIAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )

        schema = adapter._create_trajectory_schema()

        # Check schema structure
        assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
        assert schema["type"] == "object"
        assert "task_id" in schema["required"]
        assert "steps" in schema["required"]
        assert "final_state" in schema["required"]
        # Check steps structure
        assert "steps" in schema["properties"]
        assert "items" in schema["properties"]["steps"]

    def test_test_sh_contains_trajectory_validation(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test generated test.sh validates trajectory file."""
        adapter = DevAIAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )
        out_dir = adapter.generate_task("devai-web-001")

        test_sh_content = (out_dir / "tests" / "test.sh").read_text()

        # Check for trajectory validation logic
        assert "trajectory" in test_sh_content.lower()
        assert "verify.py" in test_sh_content
        assert "ground_truth.json" in test_sh_content
        assert "trajectory-schema.json" in test_sh_content

    def test_verify_py_can_be_imported(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test that verify.py is syntactically valid Python."""
        import ast

        adapter = DevAIAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )
        out_dir = adapter.generate_task("devai-web-001")

        verify_py_content = (out_dir / "tests" / "verify.py").read_text()

        # Try to parse the Python code - will raise SyntaxError if invalid
        ast.parse(verify_py_content)
