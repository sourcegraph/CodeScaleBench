#!/usr/bin/env python3
"""Tests for scripts/abc_score_task.py — ABC Task Quality Scorer."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from abc_score_task import (
    DimensionScore,
    TaskScore,
    discover_all_suites,
    discover_tasks,
    format_table,
    parse_task_toml_simple,
    score_instruction_clarity,
    score_reproducibility,
    score_task,
    score_verifier_quality,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_task(tmp_path):
    """Create a minimal valid task directory."""
    task_dir = tmp_path / "ccb_test" / "test-task-001"
    task_dir.mkdir(parents=True)

    # task.toml
    (task_dir / "task.toml").write_text(
        '[task]\nname = "test-task-001"\n\n[metadata]\ndifficulty = "medium"\n'
    )

    # instruction.md
    (task_dir / "instruction.md").write_text(
        "# Task: Fix the Widget\n\n"
        "## Background\n\n"
        "The widget module has a bug in the sorting algorithm.\n"
        "- The sort is unstable when duplicate keys exist\n"
        "- This causes flaky test failures in CI\n\n"
        "## Requirements\n\n"
        "Fix the sorting implementation in `widget.py` to use a stable sort.\n"
        "Ensure all existing tests pass.\n"
        "A" * 400  # Pad to >500 chars
    )

    # tests/test.sh
    tests_dir = task_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "test.sh").write_text(
        "#!/bin/bash\n"
        "set -eo pipefail\n\n"
        "cd /workspace\n"
        "python -m pytest tests/ -v\n"
        "RESULT=$?\n\n"
        "if [ $RESULT -eq 0 ]; then\n"
        '  echo "1.0" > /logs/verifier/reward.txt\n'
        "else\n"
        '  echo "0.0" > /logs/verifier/reward.txt\n'
        "fi\n"
    )

    # environment/Dockerfile
    env_dir = task_dir / "environment"
    env_dir.mkdir()
    (env_dir / "Dockerfile").write_text(
        "FROM python:3.10.12-slim\n"
        "WORKDIR /workspace\n"
        "RUN pip install pytest==7.4.0\n"
    )

    return task_dir


@pytest.fixture
def minimal_task(tmp_path):
    """Create a barely-there task directory."""
    task_dir = tmp_path / "ccb_minimal" / "bare-001"
    task_dir.mkdir(parents=True)
    (task_dir / "task.toml").write_text('name = "bare-001"\n')
    (task_dir / "instruction.md").write_text("Fix it.")
    return task_dir


@pytest.fixture
def rich_task(tmp_path):
    """Create a fully-featured task directory."""
    task_dir = tmp_path / "ccb_rich" / "rich-001"
    task_dir.mkdir(parents=True)

    (task_dir / "task.toml").write_text(
        '[task]\nname = "rich-001"\ntime_limit_sec = 600\n'
        "memory_limit = 4096\n\n"
        '[metadata]\ndifficulty = "hard"\n'
    )

    (task_dir / "instruction.md").write_text(
        "# Rich Task\n\n"
        "## Overview\n\n"
        "- Step 1: Understand the codebase\n"
        "- Step 2: Implement the fix\n"
        "- Step 3: Run tests\n\n"
        "This is a detailed instruction with plenty of context.\n"
        "A" * 600
    )

    # solve.sh (ground truth)
    (task_dir / "solve.sh").write_text("#!/bin/bash\npatch -p1 < fix.patch\n")

    tests_dir = task_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "test.sh").write_text(
        "#!/bin/bash\n"
        "set -eo pipefail\n\n"
        "cd /workspace\n"
        "# Multiple assertions\n"
        "diff output.txt expected.txt\n"
        "grep -q 'SUCCESS' result.log\n"
        "test -f /workspace/output.txt\n"
        "python -c \"assert True\"\n\n"
        "# Partial credit scoring\n"
        "SCORE=0.0\n"
        "if diff -q a b; then SCORE=$(echo \"$SCORE + 0.5\" | bc -l); fi\n"
        "if grep -q ok c; then SCORE=$(echo \"$SCORE + 0.5\" | bc -l); fi\n"
        'echo "$SCORE" > /logs/verifier/reward.txt\n'
    )

    env_dir = task_dir / "environment"
    env_dir.mkdir()
    (env_dir / "Dockerfile").write_text(
        "FROM ubuntu:22.04\n"
        "RUN apt-get update && apt-get install -y python3=3.10.6-1~22.04\n"
        "RUN git clone https://github.com/example/repo.git /workspace\n"
        "RUN cd /workspace && git checkout abc123def456\n"
    )

    return task_dir


# ---------------------------------------------------------------------------
# TOML parser
# ---------------------------------------------------------------------------

class TestTomlParser:
    def test_basic_parse(self, tmp_path):
        f = tmp_path / "task.toml"
        f.write_text('[task]\nname = "hello"\ntime_limit_sec = 300\n')
        result = parse_task_toml_simple(f)
        assert result["task.name"] == "hello"
        assert result["task.time_limit_sec"] == "300"

    def test_missing_file(self, tmp_path):
        result = parse_task_toml_simple(tmp_path / "nope.toml")
        assert result == {}

    def test_flat_keys(self, tmp_path):
        f = tmp_path / "task.toml"
        f.write_text('name = "flat"\ndifficulty = "easy"\n')
        result = parse_task_toml_simple(f)
        assert result["name"] == "flat"
        assert result["difficulty"] == "easy"


# ---------------------------------------------------------------------------
# Instruction Clarity
# ---------------------------------------------------------------------------

class TestInstructionClarity:
    def test_good_instruction(self, tmp_task):
        toml = parse_task_toml_simple(tmp_task / "task.toml")
        dim = score_instruction_clarity(tmp_task, toml)
        assert dim.name == "instruction_clarity"
        assert dim.weight == 0.30
        assert dim.score > 0.7
        assert dim.sub_checks["length"] == 1.0
        assert dim.sub_checks["structure"] == 1.0
        assert dim.sub_checks["no_placeholders"] == 1.0

    def test_short_instruction(self, minimal_task):
        toml = parse_task_toml_simple(minimal_task / "task.toml")
        dim = score_instruction_clarity(minimal_task, toml)
        assert dim.sub_checks["length"] == 0.0
        assert dim.sub_checks["structure"] == 0.0

    def test_missing_instruction(self, tmp_path):
        task = tmp_path / "no_inst"
        task.mkdir()
        (task / "task.toml").write_text('name = "x"\n')
        dim = score_instruction_clarity(task, {})
        assert dim.score == 0.0

    def test_placeholder_detection(self, tmp_path):
        task = tmp_path / "placeholders"
        task.mkdir()
        (task / "instruction.md").write_text(
            "# Task\n\n" + "Fix {{PLACEHOLDER}} in the code. TODO: add details.\n" + "A" * 500
        )
        (task / "task.toml").write_text('[task]\nname = "ph"\n[metadata]\ndifficulty = "easy"\n')
        toml = parse_task_toml_simple(task / "task.toml")
        dim = score_instruction_clarity(task, toml)
        assert dim.sub_checks["no_placeholders"] == 0.0

    def test_metadata_completeness(self, tmp_path):
        task = tmp_path / "meta"
        task.mkdir()
        (task / "instruction.md").write_text("# T\n" + "A" * 600)
        # Has name but no difficulty
        (task / "task.toml").write_text('[task]\nname = "meta"\n')
        toml = parse_task_toml_simple(task / "task.toml")
        dim = score_instruction_clarity(task, toml)
        assert dim.sub_checks["metadata_complete"] == 0.5


# ---------------------------------------------------------------------------
# Verifier Quality
# ---------------------------------------------------------------------------

class TestVerifierQuality:
    def test_good_verifier(self, tmp_task):
        dim = score_verifier_quality(tmp_task)
        assert dim.name == "verifier_quality"
        assert dim.weight == 0.40
        assert dim.sub_checks["exists"] == 1.0
        assert dim.sub_checks["error_handling"] == 1.0
        assert dim.sub_checks["reward_output"] == 1.0

    def test_no_verifier(self, tmp_path):
        task = tmp_path / "no_verifier"
        task.mkdir()
        dim = score_verifier_quality(task)
        assert dim.score == 0.0
        assert dim.sub_checks["exists"] == 0.0

    def test_rich_verifier(self, rich_task):
        dim = score_verifier_quality(rich_task)
        assert dim.sub_checks["exists"] == 1.0
        assert dim.sub_checks["error_handling"] == 1.0
        assert dim.sub_checks["nontrivial_logic"] == 1.0
        assert dim.sub_checks["ground_truth"] == 1.0
        assert dim.sub_checks["partial_credit"] == 1.0
        assert dim.score > 0.8

    def test_no_error_handling(self, tmp_path):
        task = tmp_path / "no_err"
        task.mkdir()
        tests = task / "tests"
        tests.mkdir()
        (tests / "test.sh").write_text(
            "#!/bin/bash\n"
            "python test.py\n"
            'echo "1.0" > /logs/verifier/reward.txt\n'
        )
        dim = score_verifier_quality(task)
        assert dim.sub_checks["error_handling"] == 0.0

    def test_python_verifier_gets_error_handling_credit(self, tmp_path):
        task = tmp_path / "py_verifier"
        task.mkdir()
        tests = task / "tests"
        tests.mkdir()
        (tests / "verify.py").write_text(
            "import json\n"
            "score = 0.5\n"
            "with open('/logs/verifier/reward.txt', 'w') as f:\n"
            "    f.write(str(score))\n"
        )
        dim = score_verifier_quality(task)
        assert dim.sub_checks["error_handling"] == 1.0


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------

class TestReproducibility:
    def test_good_reproducibility(self, rich_task):
        toml = parse_task_toml_simple(rich_task / "task.toml")
        dim = score_reproducibility(rich_task, toml)
        assert dim.name == "reproducibility"
        assert dim.weight == 0.30
        assert dim.sub_checks["dockerfile_exists"] == 1.0
        assert dim.sub_checks["time_limit_set"] == 1.0
        assert dim.sub_checks["resource_limits"] == 1.0
        assert dim.sub_checks["deterministic_checkout"] == 1.0

    def test_no_dockerfile(self, minimal_task):
        toml = parse_task_toml_simple(minimal_task / "task.toml")
        dim = score_reproducibility(minimal_task, toml)
        assert dim.sub_checks["dockerfile_exists"] == 0.0

    def test_unpinned_latest(self, tmp_path):
        task = tmp_path / "unpinned"
        task.mkdir()
        env = task / "environment"
        env.mkdir()
        (env / "Dockerfile").write_text("FROM python:latest\nRUN pip install flask\n")
        (task / "task.toml").write_text('name = "x"\n')
        toml = parse_task_toml_simple(task / "task.toml")
        dim = score_reproducibility(task, toml)
        assert dim.sub_checks["pinned_versions"] == 0.0

    def test_unpinned_git_clone(self, tmp_path):
        task = tmp_path / "clone"
        task.mkdir()
        env = task / "environment"
        env.mkdir()
        (env / "Dockerfile").write_text(
            "FROM ubuntu:22.04\n"
            "RUN git clone --depth 1 https://github.com/example/repo /workspace\n"
        )
        (task / "task.toml").write_text('name = "x"\n')
        toml = parse_task_toml_simple(task / "task.toml")
        dim = score_reproducibility(task, toml)
        assert dim.sub_checks["deterministic_checkout"] == 0.0


# ---------------------------------------------------------------------------
# TaskScore
# ---------------------------------------------------------------------------

class TestTaskScore:
    def test_compute_overall(self):
        ts = TaskScore(task_id="t1", suite="s", task_dir="d")
        ts.dimensions = [
            DimensionScore(name="a", weight=0.30, score=1.0),
            DimensionScore(name="b", weight=0.40, score=0.5),
            DimensionScore(name="c", weight=0.30, score=0.0),
        ]
        ts.compute_overall()
        expected = 0.30 * 1.0 + 0.40 * 0.5 + 0.30 * 0.0
        assert abs(ts.overall - round(expected, 3)) < 0.001

    def test_to_dict(self):
        ts = TaskScore(task_id="t1", suite="s", task_dir="d", overall=0.75)
        ts.dimensions = [
            DimensionScore(name="x", weight=0.5, score=0.8, sub_checks={"a": 1.0}),
        ]
        d = ts.to_dict()
        assert d["task_id"] == "t1"
        assert d["overall"] == 0.75
        assert len(d["dimensions"]) == 1
        assert d["dimensions"][0]["sub_checks"]["a"] == 1.0

    def test_empty_dimensions(self):
        ts = TaskScore(task_id="t1", suite="s", task_dir="d")
        ts.compute_overall()
        assert ts.overall == 0.0


# ---------------------------------------------------------------------------
# Integration: score_task
# ---------------------------------------------------------------------------

class TestScoreTask:
    def test_score_full_task(self, tmp_task):
        result = score_task(tmp_task)
        assert result.task_id == "test-task-001"
        assert result.suite == "ccb_test"
        assert len(result.dimensions) == 3
        assert 0.0 <= result.overall <= 1.0

    def test_score_minimal_task(self, minimal_task):
        result = score_task(minimal_task)
        assert result.overall < 0.5  # Should be low

    def test_score_rich_task(self, rich_task):
        result = score_task(rich_task)
        assert result.overall > 0.6  # Should be decent


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_discover_tasks_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("abc_score_task.BENCHMARKS_DIR", tmp_path)
        assert discover_tasks("nonexistent") == []

    def test_discover_tasks(self, tmp_path, monkeypatch):
        monkeypatch.setattr("abc_score_task.BENCHMARKS_DIR", tmp_path)
        suite_dir = tmp_path / "ccb_test"
        suite_dir.mkdir()
        t1 = suite_dir / "task-a"
        t1.mkdir()
        (t1 / "task.toml").write_text('name = "a"\n')
        t2 = suite_dir / "task-b"
        t2.mkdir()
        (t2 / "instruction.md").write_text("Do something")
        # Skip hidden dirs
        (suite_dir / ".hidden").mkdir()
        result = discover_tasks("ccb_test")
        assert len(result) == 2

    def test_discover_all_suites(self, tmp_path, monkeypatch):
        monkeypatch.setattr("abc_score_task.BENCHMARKS_DIR", tmp_path)
        (tmp_path / "ccb_a").mkdir()
        (tmp_path / "ccb_b").mkdir()
        (tmp_path / "other").mkdir()  # Should be excluded
        suites = discover_all_suites()
        assert suites == ["ccb_a", "ccb_b"]


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

class TestFormatTable:
    def test_basic_table(self):
        scores = [
            TaskScore(task_id="task-001", suite="ccb_test", task_dir="d", overall=0.85),
            TaskScore(task_id="task-002", suite="ccb_test", task_dir="d", overall=0.55, needs_review=True),
        ]
        for s in scores:
            s.dimensions = [
                DimensionScore(name="instruction_clarity", weight=0.3, score=0.8),
                DimensionScore(name="verifier_quality", weight=0.4, score=0.9),
                DimensionScore(name="reproducibility", weight=0.3, score=0.7),
            ]
        table = format_table(scores, 0.7)
        assert "task-001" in table
        assert "task-002" in table
        assert "*" in table  # Flagged task
        assert "Flagged" in table
