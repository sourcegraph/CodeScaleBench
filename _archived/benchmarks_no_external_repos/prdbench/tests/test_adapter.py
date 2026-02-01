"""
Tests for PRDBench data model, loader, and adapter.
"""

import json
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from benchmarks.prdbench.adapter import (
    EvaluationCriterion,
    PRDBenchLoader,
    PRDBenchTask,
    EvaluationPlan,
    PRDBenchAdapter,
)


class TestEvaluationCriterion:
    """Tests for the EvaluationCriterion dataclass."""

    def test_criterion_creation(self) -> None:
        """Test creating a criterion with default values."""
        criterion = EvaluationCriterion(
            id="C1",
            name="User Authentication",
            description="Verify user authentication works correctly",
        )
        assert criterion.id == "C1"
        assert criterion.name == "User Authentication"
        assert criterion.description == "Verify user authentication works correctly"
        assert criterion.weight == 1.0
        assert criterion.category == "functional"
        assert criterion.automated is False

    def test_criterion_with_all_fields(self) -> None:
        """Test creating a criterion with all fields specified."""
        criterion = EvaluationCriterion(
            id="C2",
            name="Performance",
            description="Page load time under 2 seconds",
            weight=0.5,
            category="performance",
            automated=True,
        )
        assert criterion.id == "C2"
        assert criterion.weight == 0.5
        assert criterion.category == "performance"
        assert criterion.automated is True

    def test_criterion_to_dict(self) -> None:
        """Test converting criterion to dictionary."""
        criterion = EvaluationCriterion(
            id="C3",
            name="UI Consistency",
            description="UI follows design system",
            weight=0.75,
            category="ui",
            automated=False,
        )
        result = criterion.to_dict()

        assert result["id"] == "C3"
        assert result["name"] == "UI Consistency"
        assert result["description"] == "UI follows design system"
        assert result["weight"] == 0.75
        assert result["category"] == "ui"
        assert result["automated"] is False

    def test_criterion_from_dict(self) -> None:
        """Test creating criterion from dictionary."""
        data = {
            "id": "C4",
            "name": "Data Validation",
            "description": "Input validation prevents invalid data",
            "weight": 0.8,
            "category": "security",
            "automated": True,
        }
        criterion = EvaluationCriterion.from_dict(data)

        assert criterion.id == "C4"
        assert criterion.name == "Data Validation"
        assert criterion.description == "Input validation prevents invalid data"
        assert criterion.weight == 0.8
        assert criterion.category == "security"
        assert criterion.automated is True

    def test_criterion_from_dict_with_defaults(self) -> None:
        """Test criterion from_dict uses defaults for missing fields."""
        data = {"id": "C5", "name": "Basic", "description": "Basic test"}
        criterion = EvaluationCriterion.from_dict(data)

        assert criterion.id == "C5"
        assert criterion.weight == 1.0
        assert criterion.category == "functional"
        assert criterion.automated is False


class TestEvaluationPlan:
    """Tests for the EvaluationPlan dataclass."""

    def test_test_plan_creation_minimal(self) -> None:
        """Test creating a test plan with minimal fields."""
        plan = EvaluationPlan(
            version="1.0",
            task_id="prdbench-001",
        )
        assert plan.version == "1.0"
        assert plan.task_id == "prdbench-001"
        assert plan.criteria == []
        assert plan.test_cases == []
        assert plan.scoring == {}

    def test_test_plan_creation_full(self) -> None:
        """Test creating a test plan with all fields."""
        criteria = [
            EvaluationCriterion(id="C1", name="Auth", description="Auth works"),
            EvaluationCriterion(id="C2", name="API", description="API works"),
        ]
        test_cases = [
            {"id": "TC1", "name": "Login test", "steps": ["go to login", "enter creds"]},
        ]
        scoring = {"pass_threshold": 0.7, "weights": {"C1": 0.6, "C2": 0.4}}

        plan = EvaluationPlan(
            version="2.0",
            task_id="prdbench-002",
            criteria=criteria,
            test_cases=test_cases,
            scoring=scoring,
            metadata={"author": "test"},
        )

        assert plan.version == "2.0"
        assert len(plan.criteria) == 2
        assert len(plan.test_cases) == 1
        assert plan.scoring["pass_threshold"] == 0.7
        assert plan.metadata["author"] == "test"

    def test_test_plan_to_dict(self) -> None:
        """Test converting test plan to dictionary."""
        plan = EvaluationPlan(
            version="1.0",
            task_id="prdbench-003",
            criteria=[
                EvaluationCriterion(id="C1", name="Test", description="Desc"),
            ],
            scoring={"threshold": 0.5},
        )
        result = plan.to_dict()

        assert result["version"] == "1.0"
        assert result["task_id"] == "prdbench-003"
        assert len(result["criteria"]) == 1
        assert result["criteria"][0]["id"] == "C1"
        assert result["scoring"]["threshold"] == 0.5

    def test_test_plan_from_dict(self) -> None:
        """Test creating test plan from dictionary."""
        data = {
            "version": "1.5",
            "task_id": "prdbench-004",
            "criteria": [
                {"id": "C1", "name": "Crit1", "description": "Desc1", "weight": 0.7},
                {"id": "C2", "name": "Crit2", "description": "Desc2", "weight": 0.3},
            ],
            "test_cases": [{"id": "TC1", "description": "Test case 1"}],
            "scoring": {"method": "weighted"},
            "metadata": {"version_info": "v1"},
        }
        plan = EvaluationPlan.from_dict(data)

        assert plan.version == "1.5"
        assert plan.task_id == "prdbench-004"
        assert len(plan.criteria) == 2
        assert plan.criteria[0].weight == 0.7
        assert len(plan.test_cases) == 1
        assert plan.scoring["method"] == "weighted"

    def test_test_plan_get_total_weight(self) -> None:
        """Test getting total weight of criteria."""
        plan = EvaluationPlan(
            version="1.0",
            task_id="prdbench-005",
            criteria=[
                EvaluationCriterion(id="C1", name="A", description="A", weight=0.5),
                EvaluationCriterion(id="C2", name="B", description="B", weight=0.3),
                EvaluationCriterion(id="C3", name="C", description="C", weight=0.2),
            ],
        )
        total = plan.get_total_weight()
        assert abs(total - 1.0) < 0.0001

    def test_test_plan_get_criteria_by_category(self) -> None:
        """Test filtering criteria by category."""
        plan = EvaluationPlan(
            version="1.0",
            task_id="prdbench-006",
            criteria=[
                EvaluationCriterion(id="C1", name="A", description="A", category="functional"),
                EvaluationCriterion(id="C2", name="B", description="B", category="ui"),
                EvaluationCriterion(id="C3", name="C", description="C", category="functional"),
            ],
        )
        functional = plan.get_criteria_by_category("functional")

        assert len(functional) == 2
        for c in functional:
            assert c.category == "functional"

    def test_test_plan_criterion_count(self) -> None:
        """Test getting criterion count."""
        plan = EvaluationPlan(
            version="1.0",
            task_id="prdbench-007",
            criteria=[
                EvaluationCriterion(id="C1", name="A", description="A"),
                EvaluationCriterion(id="C2", name="B", description="B"),
            ],
        )
        assert plan.criterion_count() == 2


class TestPRDBenchTask:
    """Tests for the PRDBenchTask dataclass."""

    def test_task_creation_minimal(self) -> None:
        """Test creating a task with minimal fields."""
        task = PRDBenchTask(
            id="prdbench-001",
            prd_content="# My PRD\n\nBuild something cool.",
        )
        assert task.id == "prdbench-001"
        assert "My PRD" in task.prd_content
        assert task.test_plan is None
        assert task.evaluation_criteria == []
        assert task.difficulty == "medium"

    def test_task_creation_with_test_plan(self) -> None:
        """Test creating a task with a test plan."""
        test_plan = EvaluationPlan(
            version="1.0",
            task_id="prdbench-002",
            criteria=[
                EvaluationCriterion(id="C1", name="Auth", description="Auth works"),
            ],
        )

        task = PRDBenchTask(
            id="prdbench-002",
            prd_content="# PRD with test plan",
            test_plan=test_plan,
            title="Test Task",
        )

        assert task.test_plan is not None
        assert task.test_plan.version == "1.0"
        # evaluation_criteria should be populated from test_plan
        assert len(task.evaluation_criteria) == 1
        assert task.evaluation_criteria[0].id == "C1"

    def test_task_creation_with_evaluation_criteria(self) -> None:
        """Test creating a task with evaluation criteria creates test_plan."""
        criteria = [
            EvaluationCriterion(id="C1", name="Crit1", description="Desc1"),
            EvaluationCriterion(id="C2", name="Crit2", description="Desc2"),
        ]

        task = PRDBenchTask(
            id="prdbench-003",
            prd_content="# PRD with criteria",
            evaluation_criteria=criteria,
        )

        # test_plan should be created from evaluation_criteria
        assert task.test_plan is not None
        assert task.test_plan.task_id == "prdbench-003"
        assert len(task.test_plan.criteria) == 2

    def test_task_to_dict(self) -> None:
        """Test converting task to dictionary."""
        task = PRDBenchTask(
            id="prdbench-004",
            prd_content="# Test PRD",
            title="Test Task",
            description="A test task",
            difficulty="hard",
            evaluation_criteria=[
                EvaluationCriterion(id="C1", name="Test", description="Test desc"),
            ],
            metadata={"tags": ["test"]},
        )
        result = task.to_dict()

        assert result["id"] == "prdbench-004"
        assert result["prd_content"] == "# Test PRD"
        assert result["title"] == "Test Task"
        assert result["difficulty"] == "hard"
        assert len(result["evaluation_criteria"]) == 1
        assert result["metadata"]["tags"] == ["test"]

    def test_task_from_dict(self) -> None:
        """Test creating task from dictionary."""
        data = {
            "id": "prdbench-005",
            "prd_content": "# From Dict PRD\n\nContent here.",
            "test_plan": {
                "version": "1.0",
                "task_id": "prdbench-005",
                "criteria": [
                    {"id": "C1", "name": "Crit", "description": "Desc"},
                ],
            },
            "title": "From Dict Task",
            "difficulty": "easy",
            "metadata": {"source": "test"},
        }
        task = PRDBenchTask.from_dict(data)

        assert task.id == "prdbench-005"
        assert "From Dict PRD" in task.prd_content
        assert task.test_plan is not None
        assert task.test_plan.version == "1.0"
        assert task.title == "From Dict Task"
        assert task.difficulty == "easy"

    def test_task_get_criterion_count(self) -> None:
        """Test getting criterion count."""
        task = PRDBenchTask(
            id="prdbench-006",
            prd_content="# PRD",
            evaluation_criteria=[
                EvaluationCriterion(id="C1", name="A", description="A"),
                EvaluationCriterion(id="C2", name="B", description="B"),
                EvaluationCriterion(id="C3", name="C", description="C"),
            ],
        )
        assert task.get_criterion_count() == 3

    def test_task_get_prd_sections(self) -> None:
        """Test extracting PRD sections."""
        prd_content = """# Main Title

## Introduction

Some intro text.

## Requirements

### Functional Requirements

- Req 1
- Req 2

## Non-Functional Requirements

Performance stuff.
"""
        task = PRDBenchTask(
            id="prdbench-007",
            prd_content=prd_content,
        )
        sections = task.get_prd_sections()

        assert "Main Title" in sections
        assert "Introduction" in sections
        assert "Requirements" in sections
        assert "Functional Requirements" in sections
        assert "Non-Functional Requirements" in sections

    def test_task_extract_title_from_prd(self) -> None:
        """Test extracting title from PRD first heading."""
        task = PRDBenchTask(
            id="prdbench-008",
            prd_content="# My Awesome Product\n\nSome content.",
        )
        title = task.extract_title_from_prd()
        assert title == "My Awesome Product"

    def test_task_extract_title_from_prd_no_heading(self) -> None:
        """Test extracting title returns empty when no heading."""
        task = PRDBenchTask(
            id="prdbench-009",
            prd_content="No heading here, just content.",
        )
        title = task.extract_title_from_prd()
        assert title == ""


class TestPRDBenchLoader:
    """Tests for the PRDBenchLoader class."""

    @pytest.fixture
    def temp_data_dir(self) -> Generator[Path, None, None]:
        """Create a temporary data directory for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_loader_initialization_default(self) -> None:
        """Test loader initializes with default data directory."""
        loader = PRDBenchLoader()
        assert loader.data_dir == Path(__file__).parent.parent / "data"
        assert not loader._loaded

    def test_loader_initialization_custom_path(self, temp_data_dir: Path) -> None:
        """Test loader initializes with custom data directory."""
        loader = PRDBenchLoader(data_dir=temp_data_dir)
        assert loader.data_dir == temp_data_dir

    def test_loader_load_empty_directory(self, temp_data_dir: Path) -> None:
        """Test loader returns empty list for empty directory."""
        loader = PRDBenchLoader(data_dir=temp_data_dir)
        tasks = loader.load()
        assert tasks == []
        assert loader._loaded

    def test_loader_load_from_task_directories(self, temp_data_dir: Path) -> None:
        """Test loading tasks from individual task directories."""
        # Create task-001
        task1_dir = temp_data_dir / "task-001"
        (task1_dir / "src").mkdir(parents=True)
        (task1_dir / "evaluation").mkdir(parents=True)
        (task1_dir / "src" / "PRD.md").write_text("# Task 001 PRD\n\nBuild feature A.")
        test_plan_1 = {
            "version": "1.0",
            "criteria": [
                {"id": "C1", "name": "Feature A", "description": "Feature A works"},
            ],
        }
        (task1_dir / "evaluation" / "detailed_test_plan.json").write_text(
            json.dumps(test_plan_1)
        )

        # Create task-002
        task2_dir = temp_data_dir / "task-002"
        (task2_dir / "src").mkdir(parents=True)
        (task2_dir / "src" / "PRD.md").write_text("# Task 002 PRD\n\nBuild feature B.")
        # No test plan for task-002

        loader = PRDBenchLoader(data_dir=temp_data_dir)
        tasks = loader.load()

        assert len(tasks) == 2
        task_ids = [t.id for t in tasks]
        assert "task-001" in task_ids
        assert "task-002" in task_ids

        # Check task-001 has test plan
        task1 = next(t for t in tasks if t.id == "task-001")
        assert task1.test_plan is not None
        assert len(task1.evaluation_criteria) == 1

        # Check task-002 has no test plan
        task2 = next(t for t in tasks if t.id == "task-002")
        assert task2.test_plan is None
        assert len(task2.evaluation_criteria) == 0

    def test_loader_load_combined_file(self, temp_data_dir: Path) -> None:
        """Test loading tasks from combined tasks.json file."""
        tasks_data = [
            {
                "id": "prdbench-001",
                "prd_content": "# PRD 1",
                "title": "Task 1",
                "difficulty": "easy",
            },
            {
                "id": "prdbench-002",
                "prd_content": "# PRD 2",
                "title": "Task 2",
                "difficulty": "medium",
            },
            {
                "id": "prdbench-003",
                "prd_content": "# PRD 3",
                "title": "Task 3",
                "difficulty": "hard",
            },
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = PRDBenchLoader(data_dir=temp_data_dir)
        tasks = loader.load()

        assert len(tasks) == 3

    def test_loader_load_combined_file_with_tasks_key(self, temp_data_dir: Path) -> None:
        """Test loading from combined file with 'tasks' key."""
        data = {
            "version": "1.0",
            "tasks": [
                {"id": "prdbench-001", "prd_content": "# PRD 1"},
                {"id": "prdbench-002", "prd_content": "# PRD 2"},
            ],
        }
        (temp_data_dir / "tasks.json").write_text(json.dumps(data))

        loader = PRDBenchLoader(data_dir=temp_data_dir)
        tasks = loader.load()

        assert len(tasks) == 2

    def test_loader_load_from_manifest(self, temp_data_dir: Path) -> None:
        """Test loading tasks from manifest file."""
        # Create task directories
        task1_dir = temp_data_dir / "task-001"
        (task1_dir / "src").mkdir(parents=True)
        (task1_dir / "src" / "PRD.md").write_text("# Task 001 PRD")

        task2_dir = temp_data_dir / "task-002"
        (task2_dir / "src").mkdir(parents=True)
        (task2_dir / "src" / "PRD.md").write_text("# Task 002 PRD")

        # Create manifest
        manifest = {"tasks": ["task-001", "task-002"]}
        (temp_data_dir / "manifest.json").write_text(json.dumps(manifest))

        loader = PRDBenchLoader(data_dir=temp_data_dir)
        tasks = loader.load()

        assert len(tasks) == 2

    def test_loader_all_ids(self, temp_data_dir: Path) -> None:
        """Test getting all task IDs."""
        tasks_data = [
            {"id": "prdbench-001", "prd_content": "# PRD 1"},
            {"id": "prdbench-002", "prd_content": "# PRD 2"},
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = PRDBenchLoader(data_dir=temp_data_dir)
        ids = loader.all_ids()

        assert len(ids) == 2
        assert "prdbench-001" in ids
        assert "prdbench-002" in ids

    def test_loader_get_task(self, temp_data_dir: Path) -> None:
        """Test getting a specific task by ID."""
        tasks_data = [
            {"id": "prdbench-001", "prd_content": "# PRD 1", "difficulty": "easy"},
            {"id": "prdbench-002", "prd_content": "# PRD 2", "difficulty": "hard"},
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = PRDBenchLoader(data_dir=temp_data_dir)
        task = loader.get_task("prdbench-002")

        assert task is not None
        assert task.id == "prdbench-002"
        assert task.difficulty == "hard"

    def test_loader_get_task_not_found(self, temp_data_dir: Path) -> None:
        """Test getting a non-existent task returns None."""
        tasks_data = [{"id": "prdbench-001", "prd_content": "# PRD 1"}]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = PRDBenchLoader(data_dir=temp_data_dir)
        task = loader.get_task("prdbench-999")

        assert task is None

    def test_loader_task_count(self, temp_data_dir: Path) -> None:
        """Test getting total task count."""
        tasks_data = [
            {"id": "prdbench-001", "prd_content": "# PRD 1"},
            {"id": "prdbench-002", "prd_content": "# PRD 2"},
            {"id": "prdbench-003", "prd_content": "# PRD 3"},
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = PRDBenchLoader(data_dir=temp_data_dir)
        assert loader.task_count() == 3

    def test_loader_filter_by_difficulty(self, temp_data_dir: Path) -> None:
        """Test filtering tasks by difficulty."""
        tasks_data = [
            {"id": "prdbench-001", "prd_content": "# PRD 1", "difficulty": "easy"},
            {"id": "prdbench-002", "prd_content": "# PRD 2", "difficulty": "easy"},
            {"id": "prdbench-003", "prd_content": "# PRD 3", "difficulty": "medium"},
            {"id": "prdbench-004", "prd_content": "# PRD 4", "difficulty": "hard"},
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = PRDBenchLoader(data_dir=temp_data_dir)
        easy_tasks = loader.filter_by_difficulty("easy")

        assert len(easy_tasks) == 2
        for task in easy_tasks:
            assert task.difficulty == "easy"

    def test_loader_filter_by_difficulty_case_insensitive(
        self, temp_data_dir: Path
    ) -> None:
        """Test that difficulty filtering is case-insensitive."""
        tasks_data = [
            {"id": "prdbench-001", "prd_content": "# PRD 1", "difficulty": "EASY"},
            {"id": "prdbench-002", "prd_content": "# PRD 2", "difficulty": "Easy"},
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = PRDBenchLoader(data_dir=temp_data_dir)
        easy_tasks = loader.filter_by_difficulty("easy")

        assert len(easy_tasks) == 2

    def test_loader_filter_by_criteria_count(self, temp_data_dir: Path) -> None:
        """Test filtering tasks by criteria count."""
        tasks_data = [
            {
                "id": "prdbench-001",
                "prd_content": "# PRD 1",
                "evaluation_criteria": [
                    {"id": "C1", "name": "Crit1", "description": "Desc1"},
                ],
            },
            {
                "id": "prdbench-002",
                "prd_content": "# PRD 2",
                "evaluation_criteria": [
                    {"id": "C1", "name": "Crit1", "description": "Desc1"},
                    {"id": "C2", "name": "Crit2", "description": "Desc2"},
                    {"id": "C3", "name": "Crit3", "description": "Desc3"},
                ],
            },
            {
                "id": "prdbench-003",
                "prd_content": "# PRD 3",
                "evaluation_criteria": [
                    {"id": "C1", "name": "Crit1", "description": "Desc1"},
                    {"id": "C2", "name": "Crit2", "description": "Desc2"},
                ],
            },
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = PRDBenchLoader(data_dir=temp_data_dir)

        # Filter for tasks with at least 2 criteria
        filtered = loader.filter_by_criteria_count(min_criteria=2)
        assert len(filtered) == 2

        # Filter for tasks with at most 2 criteria
        filtered = loader.filter_by_criteria_count(max_criteria=2)
        assert len(filtered) == 2

        # Filter for tasks with exactly 2 criteria
        filtered = loader.filter_by_criteria_count(min_criteria=2, max_criteria=2)
        assert len(filtered) == 1

    def test_loader_total_criteria_count(self, temp_data_dir: Path) -> None:
        """Test getting total criteria count across all tasks."""
        tasks_data = [
            {
                "id": "prdbench-001",
                "prd_content": "# PRD 1",
                "evaluation_criteria": [
                    {"id": "C1", "name": "Crit1", "description": "Desc1"},
                    {"id": "C2", "name": "Crit2", "description": "Desc2"},
                ],
            },
            {
                "id": "prdbench-002",
                "prd_content": "# PRD 2",
                "evaluation_criteria": [
                    {"id": "C1", "name": "Crit1", "description": "Desc1"},
                    {"id": "C2", "name": "Crit2", "description": "Desc2"},
                    {"id": "C3", "name": "Crit3", "description": "Desc3"},
                ],
            },
        ]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = PRDBenchLoader(data_dir=temp_data_dir)
        total = loader.total_criteria_count()

        assert total == 5

    def test_loader_caches_loaded_tasks(self, temp_data_dir: Path) -> None:
        """Test that loader caches tasks and doesn't reload."""
        tasks_data = [{"id": "prdbench-001", "prd_content": "# PRD 1"}]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = PRDBenchLoader(data_dir=temp_data_dir)
        tasks1 = loader.load()
        tasks2 = loader.load()

        # Should be the same list object (cached)
        assert tasks1 is tasks2

    def test_loader_handles_malformed_json(self, temp_data_dir: Path) -> None:
        """Test that loader handles malformed JSON gracefully."""
        # Write valid tasks.json
        tasks_data = [{"id": "prdbench-001", "prd_content": "# PRD 1"}]
        (temp_data_dir / "tasks.json").write_text(json.dumps(tasks_data))

        loader = PRDBenchLoader(data_dir=temp_data_dir)
        tasks = loader.load()

        # Should load the valid task
        assert len(tasks) == 1

    def test_loader_reads_prd_from_directory(self, temp_data_dir: Path) -> None:
        """Test that loader correctly reads PRD.md content from directory."""
        task_dir = temp_data_dir / "my-task"
        (task_dir / "src").mkdir(parents=True)

        prd_content = """# E-Commerce Platform

## Overview
Build an e-commerce platform with cart and checkout.

## Requirements
1. User can add items to cart
2. User can checkout
"""
        (task_dir / "src" / "PRD.md").write_text(prd_content)

        loader = PRDBenchLoader(data_dir=temp_data_dir)
        tasks = loader.load()

        assert len(tasks) == 1
        task = tasks[0]
        assert task.id == "my-task"
        assert "E-Commerce Platform" in task.prd_content
        assert "add items to cart" in task.prd_content
        # Title should be extracted
        assert task.title == "E-Commerce Platform"

    def test_loader_reads_test_plan_from_directory(self, temp_data_dir: Path) -> None:
        """Test that loader correctly reads detailed_test_plan.json."""
        task_dir = temp_data_dir / "test-task"
        (task_dir / "src").mkdir(parents=True)
        (task_dir / "evaluation").mkdir(parents=True)

        (task_dir / "src" / "PRD.md").write_text("# Test Task PRD")

        test_plan = {
            "version": "2.0",
            "criteria": [
                {
                    "id": "C1",
                    "name": "Cart Functionality",
                    "description": "Cart works correctly",
                    "weight": 0.5,
                    "category": "functional",
                },
                {
                    "id": "C2",
                    "name": "Checkout Flow",
                    "description": "Checkout completes successfully",
                    "weight": 0.5,
                    "category": "functional",
                },
            ],
            "test_cases": [
                {"id": "TC1", "name": "Add item test"},
            ],
            "scoring": {"pass_threshold": 0.8},
        }
        (task_dir / "evaluation" / "detailed_test_plan.json").write_text(
            json.dumps(test_plan)
        )

        loader = PRDBenchLoader(data_dir=temp_data_dir)
        tasks = loader.load()

        assert len(tasks) == 1
        task = tasks[0]
        assert task.test_plan is not None
        assert task.test_plan.version == "2.0"
        assert len(task.test_plan.criteria) == 2
        assert task.test_plan.scoring["pass_threshold"] == 0.8
        assert len(task.evaluation_criteria) == 2

    def test_loader_reads_metadata_json(self, temp_data_dir: Path) -> None:
        """Test that loader reads optional metadata.json file."""
        task_dir = temp_data_dir / "meta-task"
        (task_dir / "src").mkdir(parents=True)

        (task_dir / "src" / "PRD.md").write_text("# Metadata Task PRD")
        metadata = {
            "difficulty": "hard",
            "author": "test",
            "tags": ["api", "backend"],
        }
        (task_dir / "metadata.json").write_text(json.dumps(metadata))

        loader = PRDBenchLoader(data_dir=temp_data_dir)
        tasks = loader.load()

        assert len(tasks) == 1
        task = tasks[0]
        assert task.difficulty == "hard"
        assert task.metadata["author"] == "test"
        assert task.metadata["tags"] == ["api", "backend"]


class TestPRDBenchAdapter:
    """Tests for the PRDBenchAdapter class."""

    @pytest.fixture
    def temp_dirs(self) -> Generator[tuple[Path, Path], None, None]:
        """Create temporary directories for data and output."""
        with tempfile.TemporaryDirectory() as data_tmpdir:
            with tempfile.TemporaryDirectory() as output_tmpdir:
                yield Path(data_tmpdir), Path(output_tmpdir)

    def _create_test_task(self, data_dir: Path, task_id: str = "test-task") -> None:
        """Helper to create a test task directory."""
        task_dir = data_dir / task_id
        (task_dir / "src").mkdir(parents=True)
        (task_dir / "evaluation").mkdir(parents=True)

        # Write PRD
        prd_content = """# Test Application

## Overview

Build a simple web application with user authentication.

## Requirements

1. User registration
2. User login/logout
3. Password reset

## Technical Stack

- Python 3.11+
- Flask or FastAPI
- SQLite database
"""
        (task_dir / "src" / "PRD.md").write_text(prd_content)

        # Write test plan
        test_plan = {
            "version": "1.0",
            "criteria": [
                {
                    "id": "C1",
                    "name": "User Registration",
                    "description": "Users can register with email and password",
                    "weight": 0.4,
                    "category": "functional",
                    "automated": True,
                },
                {
                    "id": "C2",
                    "name": "User Login",
                    "description": "Users can login with credentials",
                    "weight": 0.4,
                    "category": "functional",
                    "automated": True,
                },
                {
                    "id": "C3",
                    "name": "UI Responsiveness",
                    "description": "UI works on mobile and desktop",
                    "weight": 0.2,
                    "category": "ui",
                    "automated": False,
                },
            ],
            "scoring": {"pass_threshold": 0.7},
        }
        (task_dir / "evaluation" / "detailed_test_plan.json").write_text(
            json.dumps(test_plan)
        )

    def test_adapter_initialization(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test adapter initializes correctly."""
        data_dir, output_dir = temp_dirs
        adapter = PRDBenchAdapter(task_dir=output_dir, data_dir=data_dir)

        assert adapter.task_dir == output_dir
        assert adapter.loader.data_dir == data_dir

    def test_adapter_generate_task_creates_directory_structure(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that generate_task creates proper directory structure."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = PRDBenchAdapter(task_dir=output_dir, data_dir=data_dir)
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

    def test_adapter_generate_task_instruction_contains_prd(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that generated instruction.md contains the PRD content."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = PRDBenchAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task")

        instruction_content = (result_path / "instruction.md").read_text()

        # PRD content should be embedded
        assert "Test Application" in instruction_content
        assert "User registration" in instruction_content
        assert "Python 3.11+" in instruction_content
        assert "Flask or FastAPI" in instruction_content

    def test_adapter_generate_task_instruction_contains_criteria(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that generated instruction.md contains evaluation criteria."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = PRDBenchAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task")

        instruction_content = (result_path / "instruction.md").read_text()

        # Criteria should be listed
        assert "User Registration" in instruction_content
        assert "User Login" in instruction_content
        assert "UI Responsiveness" in instruction_content

    def test_adapter_generate_task_toml_has_metadata(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that generated task.toml has proper metadata."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = PRDBenchAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task")

        task_toml_content = (result_path / "task.toml").read_text()

        # Check metadata fields
        assert 'task_id = "test-task"' in task_toml_content
        assert "prdbench" in task_toml_content
        assert "criteria_count" in task_toml_content

    def test_adapter_generate_task_dockerfile_has_conda(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that Dockerfile uses conda environment."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = PRDBenchAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task")

        dockerfile_content = (result_path / "environment" / "Dockerfile").read_text()

        # Check for conda setup
        assert "miniconda" in dockerfile_content.lower() or "conda" in dockerfile_content.lower()
        assert "EXPOSE" in dockerfile_content

    def test_adapter_generate_task_dockerfile_has_multi_port(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that Dockerfile exposes multiple ports."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = PRDBenchAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task")

        dockerfile_content = (result_path / "environment" / "Dockerfile").read_text()

        # Check for multi-port configuration
        assert "EXPOSE" in dockerfile_content
        # Check for common ports
        assert "3000" in dockerfile_content or "5000" in dockerfile_content or "8000" in dockerfile_content

    def test_adapter_generate_task_ground_truth_has_criteria(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that ground_truth.json contains evaluation criteria."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = PRDBenchAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task")

        ground_truth_path = result_path / "tests" / "ground_truth.json"
        with open(ground_truth_path) as f:
            ground_truth = json.load(f)

        assert ground_truth["task_id"] == "test-task"
        assert "evaluation_criteria" in ground_truth
        assert len(ground_truth["evaluation_criteria"]) == 3
        assert ground_truth["evaluation_criteria"][0]["id"] == "C1"

    def test_adapter_generate_task_test_plan_copied(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that test_plan.json is created when test plan exists."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = PRDBenchAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task")

        test_plan_path = result_path / "tests" / "test_plan.json"
        assert test_plan_path.exists()

        with open(test_plan_path) as f:
            test_plan = json.load(f)

        assert test_plan["version"] == "1.0"
        assert len(test_plan["criteria"]) == 3

    def test_adapter_generate_task_test_sh_executable(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that test.sh is executable."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = PRDBenchAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task")

        test_sh_path = result_path / "tests" / "test.sh"
        # Check file has execute permission
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

        adapter = PRDBenchAdapter(task_dir=output_dir, data_dir=data_dir)
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

        adapter = PRDBenchAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task", local_task_id="custom-id")

        assert result_path.name == "custom-id"
        assert result_path.exists()
        assert (result_path / "instruction.md").exists()

    def test_adapter_generate_task_not_found_raises(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that generate_task raises ValueError for non-existent task."""
        data_dir, output_dir = temp_dirs

        adapter = PRDBenchAdapter(task_dir=output_dir, data_dir=data_dir)

        with pytest.raises(ValueError, match="Task not found"):
            adapter.generate_task("non-existent-task")

    def test_adapter_template_rendering(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that template rendering replaces placeholders correctly."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = PRDBenchAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task")

        # Check task.toml placeholders replaced
        task_toml = (result_path / "task.toml").read_text()
        assert "{task_id}" not in task_toml
        assert "{title}" not in task_toml
        assert "{difficulty}" not in task_toml

        # Check instruction.md placeholders replaced
        instruction = (result_path / "instruction.md").read_text()
        assert "{id}" not in instruction
        assert "{prd_content}" not in instruction
        assert "{criteria}" not in instruction

    def test_adapter_instruction_contains_task_id(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that instruction.md contains the task ID."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = PRDBenchAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task")

        instruction = (result_path / "instruction.md").read_text()
        assert "test-task" in instruction

    def test_adapter_formats_criteria_by_category(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test that criteria are grouped by category in instruction."""
        data_dir, output_dir = temp_dirs
        self._create_test_task(data_dir)

        adapter = PRDBenchAdapter(task_dir=output_dir, data_dir=data_dir)
        result_path = adapter.generate_task("test-task")

        instruction = (result_path / "instruction.md").read_text()

        # Check category headers are present
        assert "Functional" in instruction
        assert "Ui" in instruction  # Title case

    def test_adapter_multiple_tasks(
        self, temp_dirs: tuple[Path, Path]
    ) -> None:
        """Test generating multiple tasks."""
        data_dir, output_dir = temp_dirs

        # Create two test tasks
        self._create_test_task(data_dir, "task-001")
        self._create_test_task(data_dir, "task-002")

        adapter = PRDBenchAdapter(task_dir=output_dir, data_dir=data_dir)
        path1 = adapter.generate_task("task-001")
        path2 = adapter.generate_task("task-002")

        assert path1.exists()
        assert path2.exists()
        assert path1 != path2
        assert (path1 / "instruction.md").exists()
        assert (path2 / "instruction.md").exists()
