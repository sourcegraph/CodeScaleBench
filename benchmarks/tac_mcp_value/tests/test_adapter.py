"""
Tests for TAC MCP Value adapter.

Tests cover:
- TACTask dataclass creation and normalization
- TACLoader loading and filtering methods
- TACAdapter task generation
- MCP configuration injection
- Template rendering
"""

import json
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from benchmarks.tac_mcp_value.adapter import (
    TACTask,
    TACLoader,
    TACAdapter,
    TAC_ROLES,
    TAC_REGISTRY,
    TAC_VERSION,
)


# ============================================================================
# TACTask Tests
# ============================================================================


class TestTACTask:
    """Tests for TACTask dataclass."""

    def test_create_basic_task(self) -> None:
        """Test creating a basic TACTask."""
        task = TACTask(
            id="tac-test-task",
            tac_id="sde-test-task",
            role="SWE",
            title="Test Task",
            description="A test task",
        )

        assert task.id == "tac-test-task"
        assert task.tac_id == "sde-test-task"
        assert task.role == "SWE"
        assert task.title == "Test Task"
        assert task.description == "A test task"

    def test_role_normalization_uppercase(self) -> None:
        """Test that role is normalized to uppercase."""
        task = TACTask(
            id="tac-test",
            tac_id="sde-test",
            role="swe",
            title="Test",
        )
        assert task.role == "SWE"

    def test_role_normalization_mixed_case(self) -> None:
        """Test role normalization with mixed case."""
        task = TACTask(
            id="tac-test",
            tac_id="pm-test",
            role="Pm",
            title="Test",
        )
        assert task.role == "PM"

    def test_difficulty_normalization(self) -> None:
        """Test difficulty is normalized to lowercase."""
        task = TACTask(
            id="tac-test",
            tac_id="sde-test",
            role="SWE",
            title="Test",
            difficulty="HARD",
        )
        assert task.difficulty == "hard"

    def test_mcp_value_normalization(self) -> None:
        """Test MCP value is normalized."""
        task = TACTask(
            id="tac-test",
            tac_id="sde-test",
            role="SWE",
            title="Test",
            mcp_value="VERY_HIGH",
        )
        assert task.mcp_value == "very-high"

    def test_docker_image_auto_generation(self) -> None:
        """Test Docker image is auto-generated if not provided."""
        task = TACTask(
            id="tac-test",
            tac_id="sde-implement-hyperloglog",
            role="SWE",
            title="Test",
        )
        expected = f"{TAC_REGISTRY}/sde-implement-hyperloglog-image:{TAC_VERSION}"
        assert task.docker_image == expected

    def test_docker_image_preserved_if_provided(self) -> None:
        """Test Docker image is preserved if explicitly provided."""
        custom_image = "custom/image:latest"
        task = TACTask(
            id="tac-test",
            tac_id="sde-test",
            role="SWE",
            title="Test",
            docker_image=custom_image,
        )
        assert task.docker_image == custom_image

    def test_id_auto_generation_from_tac_id(self) -> None:
        """Test Harbor ID is auto-generated from TAC ID."""
        task = TACTask(
            id="",
            tac_id="sde-implement-hyperloglog",
            role="SWE",
            title="Test",
        )
        assert task.id == "tac-implement-hyperloglog"

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        task = TACTask(
            id="tac-test",
            tac_id="sde-test",
            role="SWE",
            title="Test Task",
            description="Description",
            language="python",
            difficulty="medium",
            mcp_value="high",
            grading_type="deterministic",
            dependencies=["gitlab"],
        )

        data = task.to_dict()

        assert data["id"] == "tac-test"
        assert data["tac_id"] == "sde-test"
        assert data["role"] == "SWE"
        assert data["title"] == "Test Task"
        assert data["description"] == "Description"
        assert data["language"] == "python"
        assert data["difficulty"] == "medium"
        assert data["mcp_value"] == "high"
        assert data["grading_type"] == "deterministic"
        assert data["dependencies"] == ["gitlab"]

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {
            "id": "tac-test",
            "tac_id": "sde-test",
            "role": "SWE",
            "title": "Test Task",
            "description": "Description",
            "language": "python",
            "difficulty": "hard",
            "mcp_value": "high",
            "grading_type": "deterministic",
            "dependencies": ["gitlab", "rocketchat"],
        }

        task = TACTask.from_dict(data)

        assert task.id == "tac-test"
        assert task.tac_id == "sde-test"
        assert task.role == "SWE"
        assert task.title == "Test Task"
        assert task.language == "python"
        assert task.difficulty == "hard"
        assert task.dependencies == ["gitlab", "rocketchat"]

    def test_from_dict_with_alternative_keys(self) -> None:
        """Test from_dict handles alternative field names."""
        data = {
            "harbor_id": "tac-test",
            "task_id": "sde-test",
            "name": "Test Task",
            "image": "custom/image:1.0",
        }

        task = TACTask.from_dict(data)

        assert task.id == "tac-test"
        assert task.tac_id == "sde-test"
        assert task.title == "Test Task"
        assert task.docker_image == "custom/image:1.0"

    def test_get_docker_image(self) -> None:
        """Test get_docker_image method."""
        task = TACTask(
            id="tac-test",
            tac_id="sde-test",
            role="SWE",
            title="Test",
            docker_image="test/image:latest",
        )
        assert task.get_docker_image() == "test/image:latest"

    def test_requires_server(self) -> None:
        """Test requires_server method."""
        task = TACTask(
            id="tac-test",
            tac_id="sde-test",
            role="SWE",
            title="Test",
            dependencies=["gitlab", "rocketchat"],
        )

        assert task.requires_server("gitlab") is True
        assert task.requires_server("GitLab") is True  # Case insensitive
        assert task.requires_server("rocketchat") is True
        assert task.requires_server("owncloud") is False

    def test_is_code_focused(self) -> None:
        """Test is_code_focused method."""
        swe_task = TACTask(
            id="tac-test",
            tac_id="sde-test",
            role="SWE",
            title="Test",
        )
        pm_task = TACTask(
            id="tac-test",
            tac_id="pm-test",
            role="PM",
            title="Test",
        )

        assert swe_task.is_code_focused() is True
        assert pm_task.is_code_focused() is False


# ============================================================================
# TACLoader Tests
# ============================================================================


class TestTACLoader:
    """Tests for TACLoader class."""

    def test_load_curated_tasks(self) -> None:
        """Test loading curated tasks when no data_dir provided."""
        loader = TACLoader()
        tasks = loader.load()

        assert len(tasks) > 0
        assert all(isinstance(t, TACTask) for t in tasks)

    def test_all_ids(self) -> None:
        """Test all_ids returns all task IDs."""
        loader = TACLoader()
        ids = loader.all_ids()

        assert len(ids) > 0
        assert all(isinstance(i, str) for i in ids)
        assert "tac-implement-hyperloglog" in ids

    def test_get_task_by_harbor_id(self) -> None:
        """Test get_task with Harbor ID."""
        loader = TACLoader()
        task = loader.get_task("tac-implement-hyperloglog")

        assert task is not None
        assert task.id == "tac-implement-hyperloglog"

    def test_get_task_by_tac_id(self) -> None:
        """Test get_task with TAC ID."""
        loader = TACLoader()
        task = loader.get_task("sde-implement-hyperloglog")

        assert task is not None
        assert task.tac_id == "sde-implement-hyperloglog"

    def test_get_task_not_found(self) -> None:
        """Test get_task returns None for unknown ID."""
        loader = TACLoader()
        task = loader.get_task("nonexistent-task")

        assert task is None

    def test_task_count(self) -> None:
        """Test task_count method."""
        loader = TACLoader()
        count = loader.task_count()

        assert count > 0
        assert count == len(loader.load())

    def test_filter_by_role_swe(self) -> None:
        """Test filtering by SWE role."""
        loader = TACLoader()
        tasks = loader.filter_by_role("SWE")

        assert len(tasks) > 0
        assert all(t.role == "SWE" for t in tasks)

    def test_filter_by_role_case_insensitive(self) -> None:
        """Test filter_by_role is case insensitive."""
        loader = TACLoader()
        tasks_upper = loader.filter_by_role("SWE")
        tasks_lower = loader.filter_by_role("swe")

        assert len(tasks_upper) == len(tasks_lower)

    def test_filter_by_role_empty_for_unknown(self) -> None:
        """Test filter_by_role returns empty for unknown role."""
        loader = TACLoader()
        tasks = loader.filter_by_role("UNKNOWN")

        assert len(tasks) == 0

    def test_filter_by_difficulty(self) -> None:
        """Test filtering by difficulty."""
        loader = TACLoader()
        hard_tasks = loader.filter_by_difficulty("hard")

        assert len(hard_tasks) > 0
        assert all(t.difficulty == "hard" for t in hard_tasks)

    def test_filter_by_mcp_value(self) -> None:
        """Test filtering by MCP value."""
        loader = TACLoader()
        high_tasks = loader.filter_by_mcp_value("high")

        assert len(high_tasks) > 0
        assert all(t.mcp_value == "high" for t in high_tasks)

    def test_filter_by_grading_type(self) -> None:
        """Test filtering by grading type."""
        loader = TACLoader()
        deterministic = loader.filter_by_grading_type("deterministic")

        assert len(deterministic) > 0
        assert all(t.grading_type == "deterministic" for t in deterministic)

    def test_get_roles(self) -> None:
        """Test get_roles returns unique roles."""
        loader = TACLoader()
        roles = loader.get_roles()

        assert "SWE" in roles
        assert len(roles) == len(set(roles))  # All unique

    def test_get_statistics(self) -> None:
        """Test get_statistics method."""
        loader = TACLoader()
        stats = loader.get_statistics()

        assert "total_tasks" in stats
        assert stats["total_tasks"] > 0
        assert "roles" in stats
        assert "difficulty_distribution" in stats
        assert "mcp_value_distribution" in stats

    def test_load_from_json_file(self) -> None:
        """Test loading tasks from a JSON file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            tasks_file = data_dir / "tasks.json"

            tasks_data = {
                "tasks": [
                    {
                        "id": "tac-custom-task",
                        "tac_id": "sde-custom-task",
                        "role": "SWE",
                        "title": "Custom Task",
                        "description": "A custom test task",
                        "difficulty": "easy",
                    }
                ]
            }

            with open(tasks_file, "w") as f:
                json.dump(tasks_data, f)

            loader = TACLoader(data_dir)
            tasks = loader.load()

            assert len(tasks) == 1
            assert tasks[0].id == "tac-custom-task"
            assert tasks[0].title == "Custom Task"


# ============================================================================
# TACAdapter Tests
# ============================================================================


@pytest.fixture
def output_dir() -> Generator[Path, None, None]:
    """Create a temporary output directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


class TestTACAdapter:
    """Tests for TACAdapter class."""

    def test_adapter_initialization(self, output_dir: Path) -> None:
        """Test adapter initialization."""
        adapter = TACAdapter(output_dir)

        assert adapter.task_dir == output_dir
        assert adapter.loader is not None

    def test_generate_task_creates_directory(self, output_dir: Path) -> None:
        """Test generate_task creates task directory."""
        adapter = TACAdapter(output_dir)
        task_path = adapter.generate_task("tac-implement-hyperloglog")

        assert task_path.exists()
        assert task_path.is_dir()

    def test_generate_task_creates_task_toml(self, output_dir: Path) -> None:
        """Test generate_task creates task.toml."""
        adapter = TACAdapter(output_dir)
        task_path = adapter.generate_task("tac-implement-hyperloglog")

        task_toml = task_path / "task.toml"
        assert task_toml.exists()

        content = task_toml.read_text()
        assert "tac-implement-hyperloglog" in content
        assert "category = \"tac_mcp_value\"" in content

    def test_generate_task_creates_instruction_md(self, output_dir: Path) -> None:
        """Test generate_task creates instruction.md."""
        adapter = TACAdapter(output_dir)
        task_path = adapter.generate_task("tac-implement-hyperloglog")

        instruction = task_path / "instruction.md"
        assert instruction.exists()

        content = instruction.read_text()
        assert "HyperLogLog" in content or "hyperloglog" in content.lower()

    def test_generate_task_creates_dockerfile(self, output_dir: Path) -> None:
        """Test generate_task creates Dockerfile."""
        adapter = TACAdapter(output_dir)
        task_path = adapter.generate_task("tac-implement-hyperloglog")

        dockerfile = task_path / "environment" / "Dockerfile"
        assert dockerfile.exists()

        content = dockerfile.read_text()
        assert "ghcr.io/theagentcompany" in content

    def test_generate_task_creates_test_sh(self, output_dir: Path) -> None:
        """Test generate_task creates test.sh."""
        adapter = TACAdapter(output_dir)
        task_path = adapter.generate_task("tac-implement-hyperloglog")

        test_sh = task_path / "tests" / "test.sh"
        assert test_sh.exists()
        assert test_sh.stat().st_mode & 0o111  # Executable

    def test_generate_task_creates_verify_py(self, output_dir: Path) -> None:
        """Test generate_task creates verify.py."""
        adapter = TACAdapter(output_dir)
        task_path = adapter.generate_task("tac-implement-hyperloglog")

        verify_py = task_path / "tests" / "verify.py"
        assert verify_py.exists()

    def test_generate_task_creates_ground_truth(self, output_dir: Path) -> None:
        """Test generate_task creates ground_truth.json."""
        adapter = TACAdapter(output_dir)
        task_path = adapter.generate_task("tac-implement-hyperloglog")

        ground_truth = task_path / "tests" / "ground_truth.json"
        assert ground_truth.exists()

        with open(ground_truth) as f:
            data = json.load(f)

        assert data["task_id"] == "tac-implement-hyperloglog"
        assert data["role"] == "SWE"

    def test_generate_task_with_custom_local_id(self, output_dir: Path) -> None:
        """Test generate_task with custom local task ID."""
        adapter = TACAdapter(output_dir)
        task_path = adapter.generate_task(
            "tac-implement-hyperloglog",
            local_task_id="custom-name",
        )

        assert task_path.name == "custom-name"
        assert task_path.exists()

    def test_generate_task_raises_for_unknown(self, output_dir: Path) -> None:
        """Test generate_task raises ValueError for unknown task."""
        adapter = TACAdapter(output_dir)

        with pytest.raises(ValueError, match="Task not found"):
            adapter.generate_task("nonexistent-task")

    def test_generate_all_tasks(self, output_dir: Path) -> None:
        """Test generate_all_tasks generates multiple tasks."""
        adapter = TACAdapter(output_dir)
        paths = adapter.generate_all_tasks()

        assert len(paths) > 0
        assert all(p.exists() for p in paths)

    def test_generate_all_tasks_with_role_filter(self, output_dir: Path) -> None:
        """Test generate_all_tasks with role filter."""
        adapter = TACAdapter(output_dir)
        paths = adapter.generate_all_tasks(role_filter="SWE")

        assert len(paths) > 0
        # All generated tasks should be SWE tasks
        for path in paths:
            ground_truth = path / "tests" / "ground_truth.json"
            with open(ground_truth) as f:
                data = json.load(f)
            assert data["role"] == "SWE"

    def test_generate_all_tasks_with_limit(self, output_dir: Path) -> None:
        """Test generate_all_tasks with limit."""
        adapter = TACAdapter(output_dir)
        paths = adapter.generate_all_tasks(limit=2)

        assert len(paths) == 2

    def test_mcp_setup_in_task_toml(self, output_dir: Path) -> None:
        """Test MCP configuration is in task.toml."""
        adapter = TACAdapter(output_dir)
        task_path = adapter.generate_task("tac-implement-hyperloglog")

        task_toml = task_path / "task.toml"
        content = task_toml.read_text()

        # Check for MCP setup script
        assert "mcp_config" in content
        assert "SOURCEGRAPH_ACCESS_TOKEN" in content
        assert "SOURCEGRAPH_URL" in content

    def test_verify_py_contains_tac_conversion(self, output_dir: Path) -> None:
        """Test verify.py contains TAC result conversion."""
        adapter = TACAdapter(output_dir)
        task_path = adapter.generate_task("tac-implement-hyperloglog")

        verify_py = task_path / "tests" / "verify.py"
        content = verify_py.read_text()

        assert "convert_tac_result" in content
        assert "checkpoints" in content
        assert "score" in content

    def test_test_sh_wraps_tac_eval(self, output_dir: Path) -> None:
        """Test test.sh wraps TAC evaluator."""
        adapter = TACAdapter(output_dir)
        task_path = adapter.generate_task("tac-implement-hyperloglog")

        test_sh = task_path / "tests" / "test.sh"
        content = test_sh.read_text()

        assert "/utils/eval.py" in content
        assert "DECRYPTION_KEY" in content


# ============================================================================
# Integration Tests
# ============================================================================


class TestIntegration:
    """Integration tests for the full adapter pipeline."""

    def test_full_pipeline(self, output_dir: Path) -> None:
        """Test full pipeline from load to generate."""
        # Load tasks
        loader = TACLoader()
        tasks = loader.load()
        assert len(tasks) > 0

        # Generate first task
        adapter = TACAdapter(output_dir)
        first_task = tasks[0]
        task_path = adapter.generate_task(first_task.id)

        # Verify complete structure
        assert (task_path / "task.toml").exists()
        assert (task_path / "instruction.md").exists()
        assert (task_path / "environment" / "Dockerfile").exists()
        assert (task_path / "tests" / "test.sh").exists()
        assert (task_path / "tests" / "verify.py").exists()
        assert (task_path / "tests" / "ground_truth.json").exists()

    def test_generated_task_toml_valid(self, output_dir: Path) -> None:
        """Test generated task.toml is valid TOML."""
        import tomllib  # Python 3.11+

        adapter = TACAdapter(output_dir)
        task_path = adapter.generate_task("tac-implement-hyperloglog")

        task_toml = task_path / "task.toml"
        content = task_toml.read_text()

        # Should parse without error
        parsed = tomllib.loads(content)
        assert "metadata" in parsed
        assert "task" in parsed
        assert "verification" in parsed

    def test_ground_truth_roundtrip(self, output_dir: Path) -> None:
        """Test ground truth can be loaded back."""
        adapter = TACAdapter(output_dir)
        task_path = adapter.generate_task("tac-implement-hyperloglog")

        ground_truth = task_path / "tests" / "ground_truth.json"

        with open(ground_truth) as f:
            data = json.load(f)

        # Can recreate TACTask from ground truth
        task = TACTask.from_dict(data)
        assert task.id == "tac-implement-hyperloglog"
        assert task.role == "SWE"
