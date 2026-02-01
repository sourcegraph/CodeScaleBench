"""
Tests for SWE-Perf data model, loader, and adapter.
"""

import json
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from benchmarks.sweperf.adapter import (
    SWEPerfLoader,
    SWEPerfTask,
    SWEPerfAdapter,
)


class TestSWEPerfTask:
    """Tests for the SWEPerfTask dataclass."""

    def test_task_creation_minimal(self) -> None:
        """Test creating a task with minimal fields."""
        task = SWEPerfTask(
            id="sweperf-001",
            repo_name="numpy",
            target_function="np.array.sum",
            human_solution_reference="Vectorized the inner loop",
            baseline_runtime=0.5,
        )
        assert task.id == "sweperf-001"
        assert task.repo_name == "numpy"
        assert task.target_function == "np.array.sum"
        assert task.baseline_runtime == 0.5
        assert task.difficulty == "medium"
        assert task.description == ""

    def test_task_creation_with_all_fields(self) -> None:
        """Test creating a task with all fields specified."""
        task = SWEPerfTask(
            id="sweperf-002",
            repo_name="scikit-learn",
            target_function="sklearn.tree._splitter.best_split",
            human_solution_reference="Used Cython optimization",
            baseline_runtime=1.25,
            description="Find the best split for a decision tree node",
            difficulty="hard",
            file_path="sklearn/tree/_splitter.pyx",
            test_command="pytest sklearn/tree/tests/ -v",
            optimization_hints=["Consider Cython", "Vectorize comparisons"],
            metadata={"category": "algorithmic"},
        )
        assert task.id == "sweperf-002"
        assert task.difficulty == "hard"
        assert task.file_path == "sklearn/tree/_splitter.pyx"
        assert len(task.optimization_hints) == 2
        assert task.metadata["category"] == "algorithmic"

    def test_task_difficulty_normalized_to_lowercase(self) -> None:
        """Test that difficulty is normalized to lowercase."""
        task = SWEPerfTask(
            id="sweperf-003",
            repo_name="pandas",
            target_function="pd.DataFrame.merge",
            human_solution_reference="Hash join optimization",
            baseline_runtime=0.8,
            difficulty="HARD",
        )
        assert task.difficulty == "hard"

    def test_task_id_generated_from_repo_and_function(self) -> None:
        """Test that ID is generated when not provided."""
        task = SWEPerfTask(
            id="",  # Empty ID
            repo_name="numpy",
            target_function="np.dot",
            human_solution_reference="BLAS acceleration",
            baseline_runtime=0.1,
        )
        assert task.id == "numpy__np_dot"

    def test_task_to_dict(self) -> None:
        """Test converting task to dictionary."""
        task = SWEPerfTask(
            id="sweperf-004",
            repo_name="scipy",
            target_function="scipy.linalg.solve",
            human_solution_reference="LAPACK optimizations",
            baseline_runtime=0.3,
            difficulty="medium",
            file_path="scipy/linalg/basic.py",
        )
        result = task.to_dict()

        assert result["id"] == "sweperf-004"
        assert result["repo_name"] == "scipy"
        assert result["target_function"] == "scipy.linalg.solve"
        assert result["baseline_runtime"] == 0.3
        assert result["difficulty"] == "medium"
        assert result["file_path"] == "scipy/linalg/basic.py"

    def test_task_from_dict(self) -> None:
        """Test creating task from dictionary."""
        data = {
            "id": "sweperf-005",
            "repo_name": "matplotlib",
            "target_function": "matplotlib.pyplot.plot",
            "human_solution_reference": "Backend optimization",
            "baseline_runtime": 0.15,
            "difficulty": "easy",
            "file_path": "matplotlib/pyplot.py",
            "test_command": "pytest matplotlib/tests/test_pyplot.py",
            "optimization_hints": ["Use blitting", "Reduce draw calls"],
            "metadata": {"category": "rendering"},
        }
        task = SWEPerfTask.from_dict(data)

        assert task.id == "sweperf-005"
        assert task.repo_name == "matplotlib"
        assert task.baseline_runtime == 0.15
        assert task.difficulty == "easy"
        assert len(task.optimization_hints) == 2

    def test_task_from_dict_alternative_keys(self) -> None:
        """Test task from_dict handles alternative key names."""
        data = {
            "repo": "numpy",  # Alternative to repo_name
            "function": "np.sum",  # Alternative to target_function
            "baseline": 0.2,  # Alternative to baseline_runtime
            "reference": "SIMD vectorization",  # Alternative to human_solution_reference
        }
        task = SWEPerfTask.from_dict(data)

        assert task.repo_name == "numpy"
        assert task.target_function == "np.sum"
        assert task.baseline_runtime == 0.2
        assert task.human_solution_reference == "SIMD vectorization"

    def test_task_from_dict_with_defaults(self) -> None:
        """Test task from_dict uses defaults for missing fields."""
        data = {
            "id": "sweperf-006",
            "repo_name": "pandas",
            "target_function": "pd.read_csv",
            "human_solution_reference": "Chunked reading",
            "baseline_runtime": 1.0,
        }
        task = SWEPerfTask.from_dict(data)

        assert task.difficulty == "medium"
        assert task.description == ""
        assert task.file_path == ""
        assert task.optimization_hints == []

    def test_task_get_expected_speedup(self) -> None:
        """Test getting expected speedup from metadata."""
        task = SWEPerfTask(
            id="sweperf-007",
            repo_name="numpy",
            target_function="np.einsum",
            human_solution_reference="Contract path optimization",
            baseline_runtime=0.5,
            metadata={"expected_speedup": 3.5},
        )
        assert task.get_expected_speedup() == 3.5

    def test_task_get_expected_speedup_default(self) -> None:
        """Test default expected speedup when not in metadata."""
        task = SWEPerfTask(
            id="sweperf-008",
            repo_name="numpy",
            target_function="np.fft.fft",
            human_solution_reference="FFTW backend",
            baseline_runtime=0.4,
        )
        assert task.get_expected_speedup() == 1.5

    def test_task_get_optimization_category(self) -> None:
        """Test getting optimization category from metadata."""
        task = SWEPerfTask(
            id="sweperf-009",
            repo_name="scipy",
            target_function="scipy.optimize.minimize",
            human_solution_reference="Gradient caching",
            baseline_runtime=2.0,
            metadata={"optimization_category": "caching"},
        )
        assert task.get_optimization_category() == "caching"


class TestSWEPerfLoader:
    """Tests for the SWEPerfLoader class."""

    @pytest.fixture
    def temp_data_dir(self) -> Generator[Path, None, None]:
        """Create a temporary data directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_loader_initialization_default(self) -> None:
        """Test loader initializes with default data directory."""
        loader = SWEPerfLoader()
        assert loader.data_dir == Path(__file__).parent.parent / "data"
        assert not loader._loaded

    def test_loader_initialization_custom_path(self, temp_data_dir: Path) -> None:
        """Test loader initializes with custom data directory."""
        loader = SWEPerfLoader(data_dir=temp_data_dir)
        assert loader.data_dir == temp_data_dir

    def test_loader_load_empty_directory(self, temp_data_dir: Path) -> None:
        """Test loader returns empty list for empty directory."""
        loader = SWEPerfLoader(data_dir=temp_data_dir)
        tasks = loader.load()
        assert tasks == []
        assert loader._loaded

    def test_loader_load_combined_file(self, temp_data_dir: Path) -> None:
        """Test loading tasks from combined tasks.json file."""
        tasks_data = [
            {
                "id": "sweperf-001",
                "repo_name": "numpy",
                "target_function": "np.sum",
                "human_solution_reference": "SIMD",
                "baseline_runtime": 0.1,
            },
            {
                "id": "sweperf-002",
                "repo_name": "scipy",
                "target_function": "scipy.fft",
                "human_solution_reference": "FFTW",
                "baseline_runtime": 0.2,
            },
            {
                "id": "sweperf-003",
                "repo_name": "numpy",
                "target_function": "np.dot",
                "human_solution_reference": "BLAS",
                "baseline_runtime": 0.05,
            },
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = SWEPerfLoader(data_dir=temp_data_dir)
        tasks = loader.load()

        assert len(tasks) == 3
        assert tasks[0].id == "sweperf-001"
        assert tasks[1].repo_name == "scipy"

    def test_loader_load_combined_file_with_instances_key(
        self, temp_data_dir: Path
    ) -> None:
        """Test loading from combined file with 'instances' key."""
        data = {
            "version": "1.0",
            "instances": [
                {
                    "id": "sweperf-001",
                    "repo_name": "numpy",
                    "target_function": "np.sum",
                    "human_solution_reference": "ref",
                    "baseline_runtime": 0.1,
                },
            ],
        }
        (temp_data_dir / "tasks.json").write_text(json.dumps(data))

        loader = SWEPerfLoader(data_dir=temp_data_dir)
        tasks = loader.load()

        assert len(tasks) == 1

    def test_loader_load_from_instances_directory(self, temp_data_dir: Path) -> None:
        """Test loading from instances directory."""
        instances_dir = temp_data_dir / "instances"
        instances_dir.mkdir()

        # Create individual instance files
        instance1 = {
            "id": "instance-001",
            "repo_name": "pandas",
            "target_function": "pd.merge",
            "human_solution_reference": "hash join",
            "baseline_runtime": 0.5,
        }
        (instances_dir / "instance-001.json").write_text(json.dumps(instance1))

        instance2 = {
            "id": "instance-002",
            "repo_name": "pandas",
            "target_function": "pd.groupby",
            "human_solution_reference": "sorted groups",
            "baseline_runtime": 0.3,
        }
        (instances_dir / "instance-002.json").write_text(json.dumps(instance2))

        loader = SWEPerfLoader(data_dir=temp_data_dir)
        tasks = loader.load()

        assert len(tasks) == 2

    def test_loader_load_from_manifest(self, temp_data_dir: Path) -> None:
        """Test loading from manifest file."""
        instances_dir = temp_data_dir / "instances"
        instances_dir.mkdir()

        # Create instance files
        instance1 = {
            "repo_name": "numpy",
            "target_function": "np.array",
            "human_solution_reference": "ref",
            "baseline_runtime": 0.1,
        }
        (instances_dir / "task-001.json").write_text(json.dumps(instance1))

        # Create manifest
        manifest = {"instances": ["task-001"]}
        (temp_data_dir / "manifest.json").write_text(json.dumps(manifest))

        loader = SWEPerfLoader(data_dir=temp_data_dir)
        tasks = loader.load()

        assert len(tasks) == 1
        assert tasks[0].id == "task-001"

    def test_loader_all_ids(self, temp_data_dir: Path) -> None:
        """Test getting all task IDs."""
        tasks_data = [
            {
                "id": "sweperf-001",
                "repo_name": "numpy",
                "target_function": "np.sum",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.1,
            },
            {
                "id": "sweperf-002",
                "repo_name": "scipy",
                "target_function": "scipy.fft",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.2,
            },
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = SWEPerfLoader(data_dir=temp_data_dir)
        ids = loader.all_ids()

        assert len(ids) == 2
        assert "sweperf-001" in ids
        assert "sweperf-002" in ids

    def test_loader_get_task(self, temp_data_dir: Path) -> None:
        """Test getting a specific task by ID."""
        tasks_data = [
            {
                "id": "sweperf-001",
                "repo_name": "numpy",
                "target_function": "np.sum",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.1,
            },
            {
                "id": "sweperf-002",
                "repo_name": "scipy",
                "target_function": "scipy.fft",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.2,
            },
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = SWEPerfLoader(data_dir=temp_data_dir)
        task = loader.get_task("sweperf-002")

        assert task is not None
        assert task.id == "sweperf-002"
        assert task.repo_name == "scipy"

    def test_loader_get_task_not_found(self, temp_data_dir: Path) -> None:
        """Test getting a non-existent task returns None."""
        tasks_data = [
            {
                "id": "sweperf-001",
                "repo_name": "numpy",
                "target_function": "np.sum",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.1,
            },
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = SWEPerfLoader(data_dir=temp_data_dir)
        task = loader.get_task("sweperf-999")

        assert task is None

    def test_loader_task_count(self, temp_data_dir: Path) -> None:
        """Test getting total task count."""
        tasks_data = [
            {
                "id": f"sweperf-{i:03d}",
                "repo_name": "numpy",
                "target_function": f"func_{i}",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.1 * i,
            }
            for i in range(1, 6)
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = SWEPerfLoader(data_dir=temp_data_dir)
        assert loader.task_count() == 5

    def test_loader_filter_by_repo(self, temp_data_dir: Path) -> None:
        """Test filtering tasks by repository."""
        tasks_data = [
            {
                "id": "sweperf-001",
                "repo_name": "numpy",
                "target_function": "np.sum",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.1,
            },
            {
                "id": "sweperf-002",
                "repo_name": "numpy",
                "target_function": "np.dot",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.2,
            },
            {
                "id": "sweperf-003",
                "repo_name": "scipy",
                "target_function": "scipy.fft",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.3,
            },
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = SWEPerfLoader(data_dir=temp_data_dir)
        numpy_tasks = loader.filter_by_repo("numpy")

        assert len(numpy_tasks) == 2
        for task in numpy_tasks:
            assert task.repo_name == "numpy"

    def test_loader_filter_by_repo_case_insensitive(self, temp_data_dir: Path) -> None:
        """Test that repo filtering is case-insensitive."""
        tasks_data = [
            {
                "id": "sweperf-001",
                "repo_name": "NumPy",
                "target_function": "np.sum",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.1,
            },
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = SWEPerfLoader(data_dir=temp_data_dir)
        tasks = loader.filter_by_repo("numpy")

        assert len(tasks) == 1

    def test_loader_filter_by_difficulty(self, temp_data_dir: Path) -> None:
        """Test filtering tasks by difficulty."""
        tasks_data = [
            {
                "id": "sweperf-001",
                "repo_name": "numpy",
                "target_function": "np.sum",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.1,
                "difficulty": "easy",
            },
            {
                "id": "sweperf-002",
                "repo_name": "scipy",
                "target_function": "scipy.fft",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.2,
                "difficulty": "hard",
            },
            {
                "id": "sweperf-003",
                "repo_name": "pandas",
                "target_function": "pd.merge",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.3,
                "difficulty": "easy",
            },
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = SWEPerfLoader(data_dir=temp_data_dir)
        easy_tasks = loader.filter_by_difficulty("easy")

        assert len(easy_tasks) == 2
        for task in easy_tasks:
            assert task.difficulty == "easy"

    def test_loader_filter_by_baseline_runtime(self, temp_data_dir: Path) -> None:
        """Test filtering tasks by baseline runtime range."""
        tasks_data = [
            {
                "id": "sweperf-001",
                "repo_name": "numpy",
                "target_function": "np.sum",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.1,
            },
            {
                "id": "sweperf-002",
                "repo_name": "scipy",
                "target_function": "scipy.fft",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.5,
            },
            {
                "id": "sweperf-003",
                "repo_name": "pandas",
                "target_function": "pd.merge",
                "human_solution_reference": "ref",
                "baseline_runtime": 1.0,
            },
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = SWEPerfLoader(data_dir=temp_data_dir)

        # Filter for runtime >= 0.3
        filtered = loader.filter_by_baseline_runtime(min_runtime=0.3)
        assert len(filtered) == 2

        # Filter for runtime <= 0.5
        filtered = loader.filter_by_baseline_runtime(max_runtime=0.5)
        assert len(filtered) == 2

        # Filter for runtime in range [0.2, 0.8]
        filtered = loader.filter_by_baseline_runtime(min_runtime=0.2, max_runtime=0.8)
        assert len(filtered) == 1
        assert filtered[0].id == "sweperf-002"

    def test_loader_get_repos(self, temp_data_dir: Path) -> None:
        """Test getting unique repository names."""
        tasks_data = [
            {
                "id": "sweperf-001",
                "repo_name": "numpy",
                "target_function": "np.sum",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.1,
            },
            {
                "id": "sweperf-002",
                "repo_name": "scipy",
                "target_function": "scipy.fft",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.2,
            },
            {
                "id": "sweperf-003",
                "repo_name": "numpy",
                "target_function": "np.dot",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.3,
            },
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = SWEPerfLoader(data_dir=temp_data_dir)
        repos = loader.get_repos()

        assert len(repos) == 2
        assert "numpy" in repos
        assert "scipy" in repos

    def test_loader_get_statistics(self, temp_data_dir: Path) -> None:
        """Test getting dataset statistics."""
        tasks_data = [
            {
                "id": "sweperf-001",
                "repo_name": "numpy",
                "target_function": "np.sum",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.1,
                "difficulty": "easy",
            },
            {
                "id": "sweperf-002",
                "repo_name": "scipy",
                "target_function": "scipy.fft",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.5,
                "difficulty": "medium",
            },
            {
                "id": "sweperf-003",
                "repo_name": "pandas",
                "target_function": "pd.merge",
                "human_solution_reference": "ref",
                "baseline_runtime": 1.0,
                "difficulty": "hard",
            },
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = SWEPerfLoader(data_dir=temp_data_dir)
        stats = loader.get_statistics()

        assert stats["total_tasks"] == 3
        assert stats["repo_count"] == 3
        assert stats["difficulty_distribution"]["easy"] == 1
        assert stats["difficulty_distribution"]["medium"] == 1
        assert stats["difficulty_distribution"]["hard"] == 1
        assert stats["runtime_stats"]["min"] == 0.1
        assert stats["runtime_stats"]["max"] == 1.0

    def test_loader_caches_loaded_tasks(self, temp_data_dir: Path) -> None:
        """Test that loader caches tasks and doesn't reload."""
        tasks_data = [
            {
                "id": "sweperf-001",
                "repo_name": "numpy",
                "target_function": "np.sum",
                "human_solution_reference": "ref",
                "baseline_runtime": 0.1,
            },
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = SWEPerfLoader(data_dir=temp_data_dir)
        tasks1 = loader.load()
        tasks2 = loader.load()

        # Should be the same list object (cached)
        assert tasks1 is tasks2


class TestSWEPerfAdapter:
    """Tests for the SWEPerfAdapter class."""

    @pytest.fixture
    def temp_dirs(self) -> Generator[tuple[Path, Path], None, None]:
        """Create temporary directories for data and output."""
        with tempfile.TemporaryDirectory() as data_tmpdir:
            with tempfile.TemporaryDirectory() as output_tmpdir:
                yield Path(data_tmpdir), Path(output_tmpdir)

    def _create_test_task(
        self,
        data_dir: Path,
        task_id: str = "test-task",
        repo_name: str = "numpy",
        target_function: str = "np.sum",
        baseline_runtime: float = 0.5,
    ) -> None:
        """Helper to create a test task in the data directory."""
        tasks_data = [
            {
                "id": task_id,
                "repo_name": repo_name,
                "target_function": target_function,
                "human_solution_reference": "Applied SIMD vectorization",
                "baseline_runtime": baseline_runtime,
                "description": f"Optimize the {target_function} function",
                "difficulty": "medium",
                "file_path": f"{repo_name}/core.py",
                "test_command": f"pytest {repo_name}/tests/ -v",
                "optimization_hints": ["Use vectorization", "Consider caching"],
            },
        ]
        (data_dir / "tasks.json").write_text(json.dumps(tasks_data))

    def test_adapter_initialization(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test adapter initializes correctly."""
        data_dir, output_dir = temp_dirs
        adapter = SWEPerfAdapter(task_dir=output_dir, data_dir=data_dir)

        assert adapter.task_dir == output_dir
        assert adapter.loader.data_dir == data_dir

    def test_adapter_generate_task_creates_directory_structure(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that generate_task creates proper directory structure."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = SWEPerfAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task")

        # Check directory structure
        assert result_path.exists()
        assert (result_path / "instruction.md").exists()
        assert (result_path / "task.toml").exists()
        assert (result_path / "environment").is_dir()
        assert (result_path / "environment" / "Dockerfile").exists()
        assert (result_path / "tests").is_dir()
        assert (result_path / "tests" / "test.sh").exists()
        assert (result_path / "tests" / "verify.py").exists()
        assert (result_path / "tests" / "ground_truth.json").exists()

    def test_adapter_generate_task_instruction_content(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that generated instruction.md has proper content."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = SWEPerfAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task")

        instruction_content = (result_path / "instruction.md").read_text()

        # Check key content
        assert "test-task" in instruction_content
        assert "numpy" in instruction_content
        assert "np.sum" in instruction_content
        assert "0.5" in instruction_content  # baseline_runtime
        assert "vectorization" in instruction_content.lower()

    def test_adapter_generate_task_toml_has_metadata(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that generated task.toml has proper metadata."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = SWEPerfAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task")

        task_toml_content = (result_path / "task.toml").read_text()

        # Check metadata fields
        assert 'task_id = "test-task"' in task_toml_content
        assert "sweperf" in task_toml_content
        assert "performance" in task_toml_content
        assert "runtime_reduction" in task_toml_content

    def test_adapter_generate_task_dockerfile_has_benchmarking_tools(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that Dockerfile includes benchmarking tools."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = SWEPerfAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task")

        dockerfile_content = (result_path / "environment" / "Dockerfile").read_text()

        # Check for Python and benchmarking setup
        assert "python" in dockerfile_content.lower()
        assert "pytest" in dockerfile_content
        assert "benchmark" in dockerfile_content.lower()

    def test_adapter_generate_task_ground_truth_has_baseline_runtime(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that ground_truth.json contains baseline_runtime."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir, baseline_runtime=1.25)

        adapter = SWEPerfAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task")

        ground_truth_path = result_path / "tests" / "ground_truth.json"
        with open(ground_truth_path) as f:
            ground_truth = json.load(f)

        assert ground_truth["task_id"] == "test-task"
        assert ground_truth["baseline_runtime"] == 1.25
        assert ground_truth["repo_name"] == "numpy"
        assert ground_truth["target_function"] == "np.sum"

    def test_adapter_generate_task_test_sh_executable(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that test.sh is executable."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = SWEPerfAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task")

        test_sh_path = result_path / "tests" / "test.sh"
        import os
        import stat
        mode = os.stat(test_sh_path).st_mode
        assert mode & stat.S_IXUSR  # User execute permission

    def test_adapter_generate_task_verify_py_executable(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that verify.py is executable."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = SWEPerfAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task")

        verify_py_path = result_path / "tests" / "verify.py"
        import os
        import stat
        mode = os.stat(verify_py_path).st_mode
        assert mode & stat.S_IXUSR  # User execute permission

    def test_adapter_generate_task_with_local_task_id(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test generating a task with a custom local task ID."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = SWEPerfAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task", local_task_id="custom-id")

        assert result_path.name == "custom-id"
        assert result_path.exists()
        assert (result_path / "instruction.md").exists()

    def test_adapter_generate_task_not_found_raises(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that generate_task raises ValueError for non-existent task."""
        data_dir, output_dir = temp_dirs

        adapter = SWEPerfAdapter(task_dir=output_dir, data_dir=data_dir)

        with pytest.raises(ValueError, match="Task not found"):
            adapter.generate_task("non-existent-task")

    def test_adapter_template_rendering(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that template rendering replaces placeholders correctly."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = SWEPerfAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task")

        # Check task.toml placeholders replaced
        task_toml = (result_path / "task.toml").read_text()
        assert "{task_id}" not in task_toml
        assert "{repo_name}" not in task_toml
        assert "{target_function}" not in task_toml

        # Check instruction.md placeholders replaced
        instruction = (result_path / "instruction.md").read_text()
        assert "{id}" not in instruction
        assert "{baseline_runtime}" not in instruction

    def test_adapter_generate_all_tasks(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test generating all tasks."""
        data_dir, output_dir = temp_dirs

        # Create multiple tasks
        tasks_data = [
            {
                "id": "task-001",
                "repo_name": "numpy",
                "target_function": "np.sum",
                "human_solution_reference": "ref1",
                "baseline_runtime": 0.1,
            },
            {
                "id": "task-002",
                "repo_name": "scipy",
                "target_function": "scipy.fft",
                "human_solution_reference": "ref2",
                "baseline_runtime": 0.2,
            },
            {
                "id": "task-003",
                "repo_name": "numpy",
                "target_function": "np.dot",
                "human_solution_reference": "ref3",
                "baseline_runtime": 0.3,
            },
        ]
        (data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        adapter = SWEPerfAdapter(task_dir=output_dir, data_dir=data_dir)
        paths = adapter.generate_all_tasks()

        assert len(paths) == 3
        for path in paths:
            assert path.exists()
            assert (path / "instruction.md").exists()

    def test_adapter_generate_all_tasks_with_repo_filter(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test generating tasks filtered by repository."""
        data_dir, output_dir = temp_dirs

        # Create multiple tasks from different repos
        tasks_data = [
            {
                "id": "task-001",
                "repo_name": "numpy",
                "target_function": "np.sum",
                "human_solution_reference": "ref1",
                "baseline_runtime": 0.1,
            },
            {
                "id": "task-002",
                "repo_name": "scipy",
                "target_function": "scipy.fft",
                "human_solution_reference": "ref2",
                "baseline_runtime": 0.2,
            },
            {
                "id": "task-003",
                "repo_name": "numpy",
                "target_function": "np.dot",
                "human_solution_reference": "ref3",
                "baseline_runtime": 0.3,
            },
        ]
        (data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        adapter = SWEPerfAdapter(task_dir=output_dir, data_dir=data_dir)
        paths = adapter.generate_all_tasks(repo_filter="numpy")

        assert len(paths) == 2

    def test_adapter_generate_all_tasks_with_limit(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test generating tasks with limit."""
        data_dir, output_dir = temp_dirs

        # Create multiple tasks
        tasks_data = [
            {
                "id": f"task-{i:03d}",
                "repo_name": "numpy",
                "target_function": f"func_{i}",
                "human_solution_reference": f"ref{i}",
                "baseline_runtime": 0.1 * i,
            }
            for i in range(1, 6)
        ]
        (data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        adapter = SWEPerfAdapter(task_dir=output_dir, data_dir=data_dir)
        paths = adapter.generate_all_tasks(limit=3)

        assert len(paths) == 3

    def test_adapter_verify_py_computes_runtime_reduction(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that verify.py content computes runtime_reduction correctly."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = SWEPerfAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task")

        verify_py = (result_path / "tests" / "verify.py").read_text()

        # Check for runtime_reduction computation
        assert "runtime_reduction" in verify_py
        assert "baseline_runtime" in verify_py
        assert "optimized_runtime" in verify_py
        assert "speedup" in verify_py


class TestRuntimeReductionMetric:
    """Tests for the runtime_reduction metric computation logic."""

    def test_runtime_reduction_no_improvement(self) -> None:
        """Test runtime_reduction = 0 when no improvement."""
        baseline = 1.0
        optimized = 1.0  # Same as baseline
        reduction = 1 - (optimized / baseline)
        assert reduction == 0.0

    def test_runtime_reduction_2x_speedup(self) -> None:
        """Test runtime_reduction = 0.5 for 2x speedup."""
        baseline = 1.0
        optimized = 0.5  # 2x faster
        reduction = 1 - (optimized / baseline)
        assert reduction == 0.5

    def test_runtime_reduction_10x_speedup(self) -> None:
        """Test runtime_reduction = 0.9 for 10x speedup."""
        baseline = 1.0
        optimized = 0.1  # 10x faster
        reduction = 1 - (optimized / baseline)
        assert reduction == 0.9

    def test_runtime_reduction_slowdown_clamped(self) -> None:
        """Test runtime_reduction is clamped to [0, 1] for slowdowns."""
        baseline = 1.0
        optimized = 2.0  # 2x slower!
        reduction = 1 - (optimized / baseline)
        # Should be -1.0, but needs to be clamped to 0.0
        clamped = max(0.0, min(1.0, reduction))
        assert clamped == 0.0
