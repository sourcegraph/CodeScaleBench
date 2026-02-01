"""Tests for AINativeBench adapter."""

import json
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from benchmarks.ainativebench.adapter import (
    AINativeBenchLoader,
    AINativeBenchTask,
    ScoringMetrics,
    TestCase,
    AINATIVEBENCH_BENCHMARKS,
    AINATIVEBENCH_VARIANTS,
)


class TestScoringMetrics:
    """Tests for ScoringMetrics dataclass."""

    def test_default_values(self) -> None:
        """Test default values for ScoringMetrics."""
        metrics = ScoringMetrics()
        assert metrics.primary_metric == "pass_rate"
        assert metrics.secondary_metrics == []
        assert metrics.thresholds == {}

    def test_custom_values(self) -> None:
        """Test custom values for ScoringMetrics."""
        metrics = ScoringMetrics(
            primary_metric="accuracy",
            secondary_metrics=["precision", "recall"],
            thresholds={"accuracy": 0.8, "precision": 0.7},
        )
        assert metrics.primary_metric == "accuracy"
        assert metrics.secondary_metrics == ["precision", "recall"]
        assert metrics.thresholds["accuracy"] == 0.8

    def test_to_dict(self) -> None:
        """Test to_dict method."""
        metrics = ScoringMetrics(
            primary_metric="f1_score",
            secondary_metrics=["accuracy"],
            thresholds={"f1_score": 0.9},
        )
        result = metrics.to_dict()
        assert result["primary_metric"] == "f1_score"
        assert result["secondary_metrics"] == ["accuracy"]
        assert result["thresholds"]["f1_score"] == 0.9


class TestTestCase:
    """Tests for TestCase dataclass."""

    def test_default_values(self) -> None:
        """Test default values for TestCase."""
        tc = TestCase(name="test_basic")
        assert tc.name == "test_basic"
        assert tc.input_data == {}
        assert tc.expected_output == {}
        assert tc.timeout_sec == 60

    def test_custom_values(self) -> None:
        """Test custom values for TestCase."""
        tc = TestCase(
            name="test_complex",
            input_data={"code": "def foo(): pass"},
            expected_output={"result": "success"},
            timeout_sec=120,
        )
        assert tc.name == "test_complex"
        assert tc.input_data["code"] == "def foo(): pass"
        assert tc.timeout_sec == 120

    def test_to_dict(self) -> None:
        """Test to_dict method."""
        tc = TestCase(
            name="test_serialize",
            input_data={"x": 1},
            expected_output={"y": 2},
            timeout_sec=30,
        )
        result = tc.to_dict()
        assert result["name"] == "test_serialize"
        assert result["input_data"]["x"] == 1
        assert result["expected_output"]["y"] == 2
        assert result["timeout_sec"] == 30


class TestAINativeBenchTask:
    """Tests for AINativeBenchTask dataclass."""

    def test_minimal_task(self) -> None:
        """Test minimal task creation."""
        task = AINativeBenchTask(
            id="repobench-easy-001",
            benchmark_name="repobench",
            variant="easy",
        )
        assert task.id == "repobench-easy-001"
        assert task.benchmark_name == "repobench"
        assert task.variant == "easy"
        assert task.test_cases == []
        assert task.description == ""

    def test_full_task(self) -> None:
        """Test task with all fields populated."""
        test_cases = [
            TestCase(name="test_1", input_data={"a": 1}),
            TestCase(name="test_2", input_data={"b": 2}),
        ]
        metrics = ScoringMetrics(
            primary_metric="exact_match",
            thresholds={"exact_match": 1.0},
        )
        task = AINativeBenchTask(
            id="crosscodeeval-hard-005",
            benchmark_name="crosscodeeval",
            variant="hard",
            test_cases=test_cases,
            scoring_metrics=metrics,
            description="Complete the function implementation",
            language="python",
            context_files=["src/utils.py", "src/main.py"],
            ground_truth={"solution": "def foo(): return 42"},
            metadata={"difficulty_score": 0.9},
        )
        assert task.id == "crosscodeeval-hard-005"
        assert len(task.test_cases) == 2
        assert task.scoring_metrics.primary_metric == "exact_match"
        assert task.language == "python"
        assert len(task.context_files) == 2
        assert task.metadata["difficulty_score"] == 0.9

    def test_to_dict(self) -> None:
        """Test to_dict serialization."""
        task = AINativeBenchTask(
            id="test-001",
            benchmark_name="repobench",
            variant="easy",
            test_cases=[TestCase(name="tc1")],
            description="Test task",
        )
        result = task.to_dict()
        assert result["id"] == "test-001"
        assert result["benchmark_name"] == "repobench"
        assert result["variant"] == "easy"
        assert len(result["test_cases"]) == 1
        assert result["description"] == "Test task"

    def test_from_dict_minimal(self) -> None:
        """Test from_dict with minimal data."""
        data: dict[str, Any] = {
            "id": "test-002",
            "benchmark_name": "repoexec",
            "variant": "medium",
        }
        task = AINativeBenchTask.from_dict(data)
        assert task.id == "test-002"
        assert task.benchmark_name == "repoexec"
        assert task.variant == "medium"

    def test_from_dict_full(self) -> None:
        """Test from_dict with full data."""
        data: dict[str, Any] = {
            "id": "test-003",
            "benchmark_name": "devbench",
            "variant": "hard",
            "test_cases": [
                {"name": "tc1", "input_data": {"x": 1}, "timeout_sec": 90},
                {"name": "tc2", "expected_output": {"y": 2}},
            ],
            "scoring_metrics": {
                "primary_metric": "bleu",
                "secondary_metrics": ["rouge"],
                "thresholds": {"bleu": 0.5},
            },
            "description": "Complete the implementation",
            "language": "java",
            "context_files": ["Main.java"],
            "ground_truth": {"code": "public void main(){}"},
            "metadata": {"source": "github"},
        }
        task = AINativeBenchTask.from_dict(data)
        assert task.id == "test-003"
        assert len(task.test_cases) == 2
        assert task.test_cases[0].name == "tc1"
        assert task.test_cases[0].timeout_sec == 90
        assert task.test_cases[1].name == "tc2"
        assert task.scoring_metrics.primary_metric == "bleu"
        assert task.language == "java"
        assert task.metadata["source"] == "github"

    def test_from_dict_defaults(self) -> None:
        """Test from_dict uses defaults for missing fields."""
        data: dict[str, Any] = {}
        task = AINativeBenchTask.from_dict(data)
        assert task.id == ""
        assert task.benchmark_name == ""
        assert task.variant == ""
        assert task.scoring_metrics.primary_metric == "pass_rate"
        assert task.language == "python"

    def test_roundtrip_serialization(self) -> None:
        """Test that to_dict -> from_dict preserves data."""
        original = AINativeBenchTask(
            id="roundtrip-001",
            benchmark_name="mdeval",
            variant="retrieval",
            test_cases=[TestCase(name="tc", input_data={"test": True})],
            scoring_metrics=ScoringMetrics(primary_metric="em"),
            description="Roundtrip test",
            language="typescript",
        )
        data = original.to_dict()
        restored = AINativeBenchTask.from_dict(data)

        assert restored.id == original.id
        assert restored.benchmark_name == original.benchmark_name
        assert restored.variant == original.variant
        assert restored.description == original.description
        assert restored.language == original.language
        assert len(restored.test_cases) == len(original.test_cases)


class TestAINativeBenchLoader:
    """Tests for AINativeBenchLoader class."""

    @pytest.fixture
    def temp_data_dir(self) -> Generator[Path, None, None]:
        """Create a temporary data directory with test tasks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)

            # Create hierarchical structure
            for benchmark in ["repobench", "crosscodeeval"]:
                for variant in ["easy", "medium"]:
                    variant_dir = data_dir / benchmark / variant
                    variant_dir.mkdir(parents=True)

                    # Create sample tasks
                    for i in range(2):
                        task_data = {
                            "id": f"{benchmark}-{variant}-{i:03d}",
                            "benchmark_name": benchmark,
                            "variant": variant,
                            "description": f"Task {i} for {benchmark} {variant}",
                            "test_cases": [{"name": f"test_{i}"}],
                        }
                        task_file = variant_dir / f"task_{i:03d}.json"
                        with open(task_file, "w") as f:
                            json.dump(task_data, f)

            yield data_dir

    @pytest.fixture
    def manifest_data_dir(self) -> Generator[Path, None, None]:
        """Create a temporary data directory with manifest structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            tasks_dir = data_dir / "tasks"
            tasks_dir.mkdir()

            task_files = []
            for i, (benchmark, variant) in enumerate([
                ("swe-bench", "hard"),
                ("devbench", "easy"),
                ("cocomic", "retrieval"),
            ]):
                task_data = {
                    "id": f"{benchmark}-{variant}-001",
                    "benchmark_name": benchmark,
                    "variant": variant,
                    "description": f"Manifest task {i}",
                }
                filename = f"{benchmark}-{variant}-001.json"
                task_files.append(filename)
                with open(tasks_dir / filename, "w") as f:
                    json.dump(task_data, f)

            # Create manifest
            manifest = {"tasks": task_files}
            with open(data_dir / "manifest.json", "w") as f:
                json.dump(manifest, f)

            yield data_dir

    def test_loader_initialization_default(self) -> None:
        """Test loader initializes with default path."""
        loader = AINativeBenchLoader()
        assert loader.data_dir is not None
        assert not loader._loaded

    def test_loader_initialization_custom_path(self, temp_data_dir: Path) -> None:
        """Test loader initializes with custom path."""
        loader = AINativeBenchLoader(data_dir=temp_data_dir)
        assert loader.data_dir == temp_data_dir

    def test_load_from_directory(self, temp_data_dir: Path) -> None:
        """Test loading tasks from hierarchical directory."""
        loader = AINativeBenchLoader(data_dir=temp_data_dir)
        tasks = loader.load()

        # 2 benchmarks * 2 variants * 2 tasks = 8 tasks
        assert len(tasks) == 8
        assert loader._loaded is True

    def test_load_from_manifest(self, manifest_data_dir: Path) -> None:
        """Test loading tasks from manifest."""
        loader = AINativeBenchLoader(data_dir=manifest_data_dir)
        tasks = loader.load()

        assert len(tasks) == 3
        task_ids = [t.id for t in tasks]
        assert "swe-bench-hard-001" in task_ids
        assert "devbench-easy-001" in task_ids
        assert "cocomic-retrieval-001" in task_ids

    def test_load_caches_result(self, temp_data_dir: Path) -> None:
        """Test that load() caches results."""
        loader = AINativeBenchLoader(data_dir=temp_data_dir)
        tasks1 = loader.load()
        tasks2 = loader.load()

        # Same list object returned
        assert tasks1 is tasks2

    def test_load_empty_directory(self) -> None:
        """Test loading from empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = AINativeBenchLoader(data_dir=tmpdir)
            tasks = loader.load()
            assert tasks == []

    def test_load_nonexistent_directory(self) -> None:
        """Test loading from nonexistent directory."""
        loader = AINativeBenchLoader(data_dir="/nonexistent/path/12345")
        tasks = loader.load()
        assert tasks == []

    def test_all_ids(self, temp_data_dir: Path) -> None:
        """Test all_ids returns correct IDs."""
        loader = AINativeBenchLoader(data_dir=temp_data_dir)
        ids = loader.all_ids()

        assert len(ids) == 8
        assert "repobench-easy-000" in ids
        assert "crosscodeeval-medium-001" in ids

    def test_filter_by_benchmark(self, temp_data_dir: Path) -> None:
        """Test filtering by benchmark name."""
        loader = AINativeBenchLoader(data_dir=temp_data_dir)
        loader.load()

        repobench_tasks = loader.filter_by_benchmark("repobench")
        assert len(repobench_tasks) == 4  # 2 variants * 2 tasks
        for task in repobench_tasks:
            assert task.benchmark_name == "repobench"

        crosscode_tasks = loader.filter_by_benchmark("crosscodeeval")
        assert len(crosscode_tasks) == 4
        for task in crosscode_tasks:
            assert task.benchmark_name == "crosscodeeval"

    def test_filter_by_benchmark_case_insensitive(
        self, temp_data_dir: Path
    ) -> None:
        """Test filter_by_benchmark is case-insensitive."""
        loader = AINativeBenchLoader(data_dir=temp_data_dir)
        loader.load()

        tasks_lower = loader.filter_by_benchmark("repobench")
        tasks_upper = loader.filter_by_benchmark("REPOBENCH")
        tasks_mixed = loader.filter_by_benchmark("RepoBench")

        assert len(tasks_lower) == len(tasks_upper) == len(tasks_mixed)

    def test_filter_by_benchmark_no_match(self, temp_data_dir: Path) -> None:
        """Test filter_by_benchmark returns empty for non-existent benchmark."""
        loader = AINativeBenchLoader(data_dir=temp_data_dir)
        loader.load()

        tasks = loader.filter_by_benchmark("nonexistent")
        assert tasks == []

    def test_filter_by_variant(self, temp_data_dir: Path) -> None:
        """Test filtering by variant."""
        loader = AINativeBenchLoader(data_dir=temp_data_dir)
        loader.load()

        easy_tasks = loader.filter_by_variant("easy")
        assert len(easy_tasks) == 4  # 2 benchmarks * 2 tasks
        for task in easy_tasks:
            assert task.variant == "easy"

        medium_tasks = loader.filter_by_variant("medium")
        assert len(medium_tasks) == 4
        for task in medium_tasks:
            assert task.variant == "medium"

    def test_filter_by_variant_case_insensitive(
        self, temp_data_dir: Path
    ) -> None:
        """Test filter_by_variant is case-insensitive."""
        loader = AINativeBenchLoader(data_dir=temp_data_dir)
        loader.load()

        tasks_lower = loader.filter_by_variant("easy")
        tasks_upper = loader.filter_by_variant("EASY")

        assert len(tasks_lower) == len(tasks_upper)

    def test_filter_by_benchmark_and_variant(self, temp_data_dir: Path) -> None:
        """Test filtering by both benchmark and variant."""
        loader = AINativeBenchLoader(data_dir=temp_data_dir)
        loader.load()

        tasks = loader.filter_by_benchmark_and_variant("repobench", "easy")
        assert len(tasks) == 2
        for task in tasks:
            assert task.benchmark_name == "repobench"
            assert task.variant == "easy"

    def test_get_task_existing(self, temp_data_dir: Path) -> None:
        """Test get_task returns task for existing ID."""
        loader = AINativeBenchLoader(data_dir=temp_data_dir)
        loader.load()

        task = loader.get_task("repobench-easy-000")
        assert task is not None
        assert task.id == "repobench-easy-000"
        assert task.benchmark_name == "repobench"

    def test_get_task_nonexistent(self, temp_data_dir: Path) -> None:
        """Test get_task returns None for non-existent ID."""
        loader = AINativeBenchLoader(data_dir=temp_data_dir)
        loader.load()

        task = loader.get_task("nonexistent-id")
        assert task is None

    def test_get_benchmarks(self, temp_data_dir: Path) -> None:
        """Test get_benchmarks returns unique benchmark names."""
        loader = AINativeBenchLoader(data_dir=temp_data_dir)
        loader.load()

        benchmarks = loader.get_benchmarks()
        assert set(benchmarks) == {"repobench", "crosscodeeval"}

    def test_get_variants(self, temp_data_dir: Path) -> None:
        """Test get_variants returns unique variants."""
        loader = AINativeBenchLoader(data_dir=temp_data_dir)
        loader.load()

        variants = loader.get_variants()
        assert set(variants) == {"easy", "medium"}

    def test_task_count(self, temp_data_dir: Path) -> None:
        """Test task_count returns correct number."""
        loader = AINativeBenchLoader(data_dir=temp_data_dir)
        assert loader.task_count() == 8

    def test_task_count_empty(self) -> None:
        """Test task_count returns 0 for empty loader."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = AINativeBenchLoader(data_dir=tmpdir)
            assert loader.task_count() == 0

    def test_auto_load_on_filter(self, temp_data_dir: Path) -> None:
        """Test that filter methods auto-load if not loaded."""
        loader = AINativeBenchLoader(data_dir=temp_data_dir)
        assert not loader._loaded

        tasks = loader.filter_by_benchmark("repobench")
        assert loader._loaded
        assert len(tasks) == 4

    def test_auto_load_on_all_ids(self, temp_data_dir: Path) -> None:
        """Test that all_ids auto-loads if not loaded."""
        loader = AINativeBenchLoader(data_dir=temp_data_dir)
        assert not loader._loaded

        ids = loader.all_ids()
        assert loader._loaded
        assert len(ids) == 8


class TestConstants:
    """Tests for module constants."""

    def test_benchmarks_list(self) -> None:
        """Test AINATIVEBENCH_BENCHMARKS contains expected benchmarks."""
        assert len(AINATIVEBENCH_BENCHMARKS) == 8
        assert "repobench" in AINATIVEBENCH_BENCHMARKS
        assert "swe-bench" in AINATIVEBENCH_BENCHMARKS
        assert "crosscodeeval" in AINATIVEBENCH_BENCHMARKS

    def test_variants_list(self) -> None:
        """Test AINATIVEBENCH_VARIANTS contains expected variants."""
        assert len(AINATIVEBENCH_VARIANTS) == 4
        assert "easy" in AINATIVEBENCH_VARIANTS
        assert "medium" in AINATIVEBENCH_VARIANTS
        assert "hard" in AINATIVEBENCH_VARIANTS
        assert "retrieval" in AINATIVEBENCH_VARIANTS


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_malformed_json_file(self) -> None:
        """Test loader handles malformed JSON gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            variant_dir = data_dir / "repobench" / "easy"
            variant_dir.mkdir(parents=True)

            # Create malformed JSON
            malformed_file = variant_dir / "malformed.json"
            with open(malformed_file, "w") as f:
                f.write("{invalid json content")

            # Create valid JSON without ID (should get auto-generated)
            valid_file = variant_dir / "valid.json"
            with open(valid_file, "w") as f:
                json.dump({"description": "valid task without ID"}, f)

            loader = AINativeBenchLoader(data_dir=data_dir)
            tasks = loader.load()

            # Should load valid task despite malformed one
            assert len(tasks) == 1
            assert tasks[0].id == "repobench-easy-valid"

    def test_task_without_id_gets_generated_id(self) -> None:
        """Test tasks without ID get auto-generated ID from filename."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            variant_dir = data_dir / "repobench" / "easy"
            variant_dir.mkdir(parents=True)

            task_file = variant_dir / "my_task_file.json"
            with open(task_file, "w") as f:
                json.dump({"description": "No ID task"}, f)

            loader = AINativeBenchLoader(data_dir=data_dir)
            tasks = loader.load()

            assert len(tasks) == 1
            assert tasks[0].id == "repobench-easy-my_task_file"

    def test_path_as_string(self) -> None:
        """Test loader accepts string path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = AINativeBenchLoader(data_dir=tmpdir)
            assert isinstance(loader.data_dir, Path)

    def test_empty_test_cases_in_from_dict(self) -> None:
        """Test from_dict handles empty test_cases."""
        data: dict[str, Any] = {
            "id": "test",
            "benchmark_name": "test",
            "variant": "easy",
            "test_cases": [],
        }
        task = AINativeBenchTask.from_dict(data)
        assert task.test_cases == []

    def test_test_case_without_name_gets_index(self) -> None:
        """Test test cases without name get indexed name."""
        data: dict[str, Any] = {
            "id": "test",
            "benchmark_name": "test",
            "variant": "easy",
            "test_cases": [
                {"input_data": {"x": 1}},
                {"input_data": {"x": 2}},
            ],
        }
        task = AINativeBenchTask.from_dict(data)
        assert task.test_cases[0].name == "test_0"
        assert task.test_cases[1].name == "test_1"


class TestAINativeBenchAdapter:
    """Tests for AINativeBenchAdapter class."""

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

            # Create hierarchical structure with sample tasks
            variant_dir = data_dir / "repobench" / "easy"
            variant_dir.mkdir(parents=True)

            task_data = {
                "id": "repobench-easy-001",
                "benchmark_name": "repobench",
                "variant": "easy",
                "description": "Complete the code snippet",
                "test_cases": [
                    {"name": "test_basic", "input_data": {"code": "def foo():"}, "timeout_sec": 30},
                    {"name": "test_edge", "input_data": {"code": "def bar():"}, "timeout_sec": 60},
                ],
                "scoring_metrics": {
                    "primary_metric": "exact_match",
                    "secondary_metrics": ["bleu"],
                    "thresholds": {"exact_match": 0.9},
                },
                "language": "python",
                "context_files": ["src/utils.py"],
                "ground_truth": {"solution": "def foo(): return 42"},
            }
            task_file = variant_dir / "task_001.json"
            with open(task_file, "w") as f:
                json.dump(task_data, f)

            yield data_dir

    def test_adapter_initialization(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test adapter initializes correctly."""
        from benchmarks.ainativebench.adapter import AINativeBenchAdapter

        adapter = AINativeBenchAdapter(
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
        from benchmarks.ainativebench.adapter import AINativeBenchAdapter

        adapter = AINativeBenchAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )
        out_dir = adapter.generate_task("repobench-easy-001")

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

    def test_generate_task_with_local_task_id(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test generate_task uses local_task_id for directory name."""
        from benchmarks.ainativebench.adapter import AINativeBenchAdapter

        adapter = AINativeBenchAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )
        out_dir = adapter.generate_task("repobench-easy-001", "my-custom-name")

        assert out_dir.name == "my-custom-name"
        assert out_dir.exists()

    def test_generate_task_instruction_md_content(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test generated instruction.md contains task information."""
        from benchmarks.ainativebench.adapter import AINativeBenchAdapter

        adapter = AINativeBenchAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )
        out_dir = adapter.generate_task("repobench-easy-001")

        instruction_content = (out_dir / "instruction.md").read_text()

        # Check content contains expected information
        assert "repobench-easy-001" in instruction_content
        assert "repobench" in instruction_content
        assert "easy" in instruction_content
        assert "python" in instruction_content
        assert "Complete the code snippet" in instruction_content

    def test_generate_task_task_toml_content(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test generated task.toml contains correct metadata."""
        from benchmarks.ainativebench.adapter import AINativeBenchAdapter

        adapter = AINativeBenchAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )
        out_dir = adapter.generate_task("repobench-easy-001")

        task_toml_content = (out_dir / "task.toml").read_text()

        # Check content contains expected information
        assert "repobench-easy-001" in task_toml_content
        assert "repobench" in task_toml_content
        assert "easy" in task_toml_content
        assert "python" in task_toml_content
        assert "ainativebench" in task_toml_content

    def test_generate_task_dockerfile_uses_python_and_uv(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test Dockerfile uses Python 3.10+ and uv package manager."""
        from benchmarks.ainativebench.adapter import AINativeBenchAdapter

        adapter = AINativeBenchAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )
        out_dir = adapter.generate_task("repobench-easy-001")

        dockerfile_content = (out_dir / "environment" / "Dockerfile").read_text()

        # Check Dockerfile content
        assert "python:3.10" in dockerfile_content
        assert "uv" in dockerfile_content
        assert "astral.sh/uv" in dockerfile_content

    def test_generate_task_ground_truth_json(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test generated ground_truth.json contains task data."""
        from benchmarks.ainativebench.adapter import AINativeBenchAdapter

        adapter = AINativeBenchAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )
        out_dir = adapter.generate_task("repobench-easy-001")

        ground_truth_path = out_dir / "tests" / "ground_truth.json"
        with open(ground_truth_path) as f:
            ground_truth = json.load(f)

        assert ground_truth["task_id"] == "repobench-easy-001"
        assert ground_truth["benchmark_name"] == "repobench"
        assert ground_truth["variant"] == "easy"
        assert len(ground_truth["test_cases"]) == 2
        assert ground_truth["scoring_metrics"]["primary_metric"] == "exact_match"

    def test_generate_task_test_sh_is_executable(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test generated test.sh has executable permissions."""
        import os
        from benchmarks.ainativebench.adapter import AINativeBenchAdapter

        adapter = AINativeBenchAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )
        out_dir = adapter.generate_task("repobench-easy-001")

        test_sh_path = out_dir / "tests" / "test.sh"
        assert os.access(test_sh_path, os.X_OK)

    def test_generate_task_verify_py_is_executable(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test generated verify.py has executable permissions."""
        import os
        from benchmarks.ainativebench.adapter import AINativeBenchAdapter

        adapter = AINativeBenchAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )
        out_dir = adapter.generate_task("repobench-easy-001")

        verify_py_path = out_dir / "tests" / "verify.py"
        assert os.access(verify_py_path, os.X_OK)

    def test_generate_task_nonexistent_raises_error(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test generate_task raises error for nonexistent task."""
        from benchmarks.ainativebench.adapter import AINativeBenchAdapter

        adapter = AINativeBenchAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )

        with pytest.raises(ValueError, match="Task not found"):
            adapter.generate_task("nonexistent-task-id")

    def test_render_template_replaces_placeholders(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test _render_template correctly replaces placeholders."""
        from benchmarks.ainativebench.adapter import AINativeBenchAdapter

        adapter = AINativeBenchAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )

        # Create a simple template file
        template_dir = temp_output_dir / "templates"
        template_dir.mkdir()
        template_file = template_dir / "test.txt"
        template_file.write_text("Task: {id}, Benchmark: {benchmark_name}")

        result = adapter._render_template(
            template_file,
            {"id": "test-001", "benchmark_name": "test-bench"},
        )

        assert result == "Task: test-001, Benchmark: test-bench"

    def test_generate_dockerfile_content(
        self, temp_output_dir: Path, temp_data_dir: Path
    ) -> None:
        """Test _generate_dockerfile returns valid Dockerfile content."""
        from benchmarks.ainativebench.adapter import AINativeBenchAdapter

        adapter = AINativeBenchAdapter(
            task_dir=temp_output_dir,
            data_dir=temp_data_dir,
        )

        dockerfile = adapter._generate_dockerfile()

        # Check essential components
        assert "FROM python:3.10" in dockerfile
        assert "apt-get" in dockerfile
        assert "uv" in dockerfile
        assert "/app" in dockerfile
        assert "/test_results" in dockerfile
        assert "CMD" in dockerfile
