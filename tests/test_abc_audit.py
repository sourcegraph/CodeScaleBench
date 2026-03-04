#!/usr/bin/env python3
"""Tests for scripts/abc_audit.py — ABC Benchmark Auditor."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from abc_audit import (
    PROJECT_CHECKS,
    SKIP_CHECKS,
    SUITE_CHECKS,
    TASK_CHECKS,
    audit_suite,
    check_oc_empty_solution_rejected,
    check_od_error_handling,
    check_oe_multiple_assertions,
    check_oh_reward_format,
    check_oi_partial_credit,
    check_r1_files_exist,
    check_r2_no_contamination,
    check_r3_readme,
    check_r5_error_catalog,
    check_r11_fingerprint_coverage,
    check_r12_repro_instructions,
    check_r13_manifest,
    check_t1_pinned_versions,
    check_t3_no_api_keys,
    check_t4_git_sha,
    check_t5_no_solution_leak,
    check_t8_oracle_exists,
    discover_all_suites,
    discover_tasks,
)
from abc_criteria import Dimension, Status


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def task_tree(tmp_path):
    """Create a benchmark suite with 2 tasks for testing."""
    suite_dir = tmp_path / "benchmarks" / "ccb_test"
    suite_dir.mkdir(parents=True)

    # README
    (suite_dir / "README.md").write_text("# Test Benchmark\nMeasures test quality.\n")

    # Task 1: Good task
    t1 = suite_dir / "good-task"
    t1.mkdir()
    (t1 / "task.toml").write_text('[task]\nname = "good-task"\n[metadata]\ndifficulty = "medium"\n')
    (t1 / "instruction.md").write_text("# Good Task\n\n- Step 1\n- Step 2\n" + "A" * 500)
    (t1 / "solve.sh").write_text("#!/bin/bash\npatch -p1 < fix.patch\n")
    tests1 = t1 / "tests"
    tests1.mkdir()
    (tests1 / "test.sh").write_text(
        "#!/bin/bash\nset -eo pipefail\n\n"
        "cd /workspace\n"
        "diff output.txt expected.txt\n"
        "grep -q 'OK' result.log\n"
        "if [ $? -eq 0 ]; then\n"
        '  echo "1.0" > /logs/verifier/reward.txt\n'
        "else\n"
        '  echo "0.0" > /logs/verifier/reward.txt\n'
        "fi\n"
    )
    env1 = t1 / "environment"
    env1.mkdir()
    (env1 / "Dockerfile").write_text("FROM python:3.10.12-slim\nRUN pip install pytest==7.4.0\n")

    # Task 2: Bad task
    t2 = suite_dir / "bad-task"
    t2.mkdir()
    (t2 / "task.toml").write_text('[task]\nname = "bad-task"\n')
    (t2 / "instruction.md").write_text(
        "Fix the bug. Use sourcegraph to search the code.\n"
    )
    tests2 = t2 / "tests"
    tests2.mkdir()
    (tests2 / "test.sh").write_text(
        "#!/bin/bash\n"
        'echo "1.0" > /logs/verifier/reward.txt\n'
    )
    env2 = t2 / "environment"
    env2.mkdir()
    (env2 / "Dockerfile").write_text(
        "FROM python:latest\n"
        "RUN git clone --depth 1 https://github.com/example/repo /workspace\n"
        "RUN pip install flask\n"
    )

    return tmp_path, suite_dir, [t1, t2]


def get_tasks(task_tree):
    """Extract task dirs from fixture."""
    return task_tree[2]


# ---------------------------------------------------------------------------
# T.1: Pinned versions
# ---------------------------------------------------------------------------

class TestT1PinnedVersions:
    def test_pass_pinned(self, task_tree):
        _, _, tasks = task_tree
        # Only check the good task
        result = check_t1_pinned_versions([tasks[0]])
        assert result.status == Status.PASS

    def test_fail_latest(self, task_tree):
        _, _, tasks = task_tree
        result = check_t1_pinned_versions([tasks[1]])
        assert result.status == Status.FAIL
        assert ":latest" in result.evidence

    def test_fail_unpinned_pip(self, task_tree):
        _, _, tasks = task_tree
        result = check_t1_pinned_versions([tasks[1]])
        assert result.status == Status.FAIL
        assert "flask" in result.evidence.lower() or "unpinned" in result.evidence.lower()


# ---------------------------------------------------------------------------
# T.3: No API keys
# ---------------------------------------------------------------------------

class TestT3NoApiKeys:
    def test_pass_no_keys(self, task_tree):
        result = check_t3_no_api_keys(get_tasks(task_tree))
        assert result.status == Status.PASS

    def test_fail_with_key(self, tmp_path):
        task = tmp_path / "key-task"
        task.mkdir()
        # Use a fake token pattern that triggers the API key detector
        fake_token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6"
        (task / "task.toml").write_text(f'api_key = "{fake_token}"\n')
        result = check_t3_no_api_keys([task])
        assert result.status == Status.FAIL


# ---------------------------------------------------------------------------
# T.4: Git SHA checkout
# ---------------------------------------------------------------------------

class TestT4GitSha:
    def test_pass_sha_checkout(self, tmp_path):
        task = tmp_path / "sha-task"
        task.mkdir()
        env = task / "environment"
        env.mkdir()
        (env / "Dockerfile").write_text(
            "FROM ubuntu:22.04\n"
            "RUN git clone https://github.com/ex/repo /ws\n"
            "RUN cd /ws && git checkout abc123def456789\n"
        )
        result = check_t4_git_sha([task])
        assert result.status == Status.PASS

    def test_fail_no_sha(self, task_tree):
        _, _, tasks = task_tree
        result = check_t4_git_sha([tasks[1]])
        assert result.status == Status.FAIL


# ---------------------------------------------------------------------------
# T.5: No solution leak
# ---------------------------------------------------------------------------

class TestT5NoSolutionLeak:
    def test_pass_no_leak(self, task_tree):
        result = check_t5_no_solution_leak(get_tasks(task_tree))
        assert result.status in (Status.PASS, Status.WARN)

    def test_detect_leak(self, tmp_path):
        task = tmp_path / "leaky"
        task.mkdir()
        (task / "instruction.md").write_text(
            "# Fix\n\nApply this exact change:\npatch -p1 < fix.patch\n"
        )
        (task / "solve.sh").write_text("#!/bin/bash\npatch -p1 < fix.patch\n")
        result = check_t5_no_solution_leak([task])
        assert result.status == Status.WARN


# ---------------------------------------------------------------------------
# T.8: Oracle exists
# ---------------------------------------------------------------------------

class TestT8OracleExists:
    def test_pass_has_oracle(self, task_tree):
        _, _, tasks = task_tree
        result = check_t8_oracle_exists([tasks[0]])
        assert result.status == Status.PASS

    def test_warn_no_oracle(self, task_tree):
        _, _, tasks = task_tree
        result = check_t8_oracle_exists([tasks[1]])
        assert result.status == Status.WARN


# ---------------------------------------------------------------------------
# O.c: Empty solution rejected
# ---------------------------------------------------------------------------

class TestOcEmptySolutionRejected:
    def test_pass_has_assertions(self, task_tree):
        _, _, tasks = task_tree
        result = check_oc_empty_solution_rejected([tasks[0]])
        assert result.status == Status.PASS

    def test_fail_unconditional(self, task_tree):
        _, _, tasks = task_tree
        result = check_oc_empty_solution_rejected([tasks[1]])
        assert result.status == Status.FAIL


# ---------------------------------------------------------------------------
# O.d: Error handling
# ---------------------------------------------------------------------------

class TestOdErrorHandling:
    def test_pass_set_e(self, task_tree):
        _, _, tasks = task_tree
        result = check_od_error_handling([tasks[0]])
        assert result.status == Status.PASS

    def test_fail_no_error_handling(self, task_tree):
        _, _, tasks = task_tree
        result = check_od_error_handling([tasks[1]])
        assert result.status == Status.FAIL


# ---------------------------------------------------------------------------
# O.e: Multiple assertions
# ---------------------------------------------------------------------------

class TestOeMultipleAssertions:
    def test_pass_multiple(self, task_tree):
        _, _, tasks = task_tree
        result = check_oe_multiple_assertions([tasks[0]])
        assert result.status == Status.PASS

    def test_warn_single(self, task_tree):
        _, _, tasks = task_tree
        result = check_oe_multiple_assertions([tasks[1]])
        assert result.status == Status.WARN


# ---------------------------------------------------------------------------
# O.h: Reward format
# ---------------------------------------------------------------------------

class TestOhRewardFormat:
    def test_pass_writes_reward(self, task_tree):
        result = check_oh_reward_format(get_tasks(task_tree))
        assert result.status == Status.PASS

    def test_fail_no_reward(self, tmp_path):
        task = tmp_path / "no-reward"
        task.mkdir()
        tests = task / "tests"
        tests.mkdir()
        (tests / "test.sh").write_text("#!/bin/bash\nset -e\npython test.py\n")
        result = check_oh_reward_format([task])
        assert result.status == Status.FAIL


# ---------------------------------------------------------------------------
# O.i: Partial credit
# ---------------------------------------------------------------------------

class TestOiPartialCredit:
    def test_pass_has_partial(self, task_tree):
        _, _, tasks = task_tree
        # good-task has 0.0/1.0 floats -> partial credit
        result = check_oi_partial_credit([tasks[0]])
        assert result.status == Status.PASS

    def test_warn_binary_only(self, tmp_path):
        task = tmp_path / "binary"
        task.mkdir()
        tests = task / "tests"
        tests.mkdir()
        (tests / "test.sh").write_text(
            '#!/bin/bash\nset -e\nif true; then echo "PASS" > reward.txt; fi\n'
        )
        result = check_oi_partial_credit([task])
        assert result.status == Status.WARN


# ---------------------------------------------------------------------------
# R.1: Files exist
# ---------------------------------------------------------------------------

class TestR1FilesExist:
    def test_pass(self, task_tree):
        result = check_r1_files_exist(get_tasks(task_tree))
        assert result.status == Status.PASS

    def test_fail_missing_instruction(self, tmp_path):
        task = tmp_path / "no-inst"
        task.mkdir()
        tests = task / "tests"
        tests.mkdir()
        (tests / "test.sh").write_text("#!/bin/bash\necho ok\n")
        result = check_r1_files_exist([task])
        assert result.status == Status.FAIL


# ---------------------------------------------------------------------------
# R.2: No contamination
# ---------------------------------------------------------------------------

class TestR2NoContamination:
    def test_pass_clean(self, task_tree):
        _, _, tasks = task_tree
        result = check_r2_no_contamination([tasks[0]])
        assert result.status == Status.PASS

    def test_fail_contaminated(self, task_tree):
        _, _, tasks = task_tree
        result = check_r2_no_contamination([tasks[1]])
        assert result.status == Status.FAIL
        assert "sourcegraph" in result.evidence.lower()


# ---------------------------------------------------------------------------
# R.3: README
# ---------------------------------------------------------------------------

class TestR3Readme:
    def test_pass_has_readme(self, task_tree, monkeypatch):
        _, suite_dir, _ = task_tree
        monkeypatch.setattr("abc_audit.BENCHMARKS_DIR", suite_dir.parent)
        result = check_r3_readme("ccb_test")
        assert result.status == Status.PASS

    def test_warn_no_readme(self, tmp_path, monkeypatch):
        suite_dir = tmp_path / "ccb_empty"
        suite_dir.mkdir()
        monkeypatch.setattr("abc_audit.BENCHMARKS_DIR", tmp_path)
        result = check_r3_readme("ccb_empty")
        assert result.status == Status.WARN


# ---------------------------------------------------------------------------
# R.5: Error catalog
# ---------------------------------------------------------------------------

class TestR5ErrorCatalog:
    def test_pass(self, tmp_path, monkeypatch):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "ERROR_CATALOG.md").write_text("# Errors\n")
        monkeypatch.setattr("abc_audit.PROJECT_ROOT", tmp_path)
        result = check_r5_error_catalog()
        assert result.status == Status.PASS

    def test_warn(self, tmp_path, monkeypatch):
        monkeypatch.setattr("abc_audit.PROJECT_ROOT", tmp_path)
        result = check_r5_error_catalog()
        assert result.status == Status.WARN


# ---------------------------------------------------------------------------
# R.11: Fingerprint coverage
# ---------------------------------------------------------------------------

class TestR11Fingerprints:
    def test_pass_enough_patterns(self, tmp_path, monkeypatch):
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        lines = ['    ("fp_%d",\n' % i for i in range(12)]
        (scripts / "status_fingerprints.py").write_text("".join(lines))
        monkeypatch.setattr("abc_audit.PROJECT_ROOT", tmp_path)
        result = check_r11_fingerprint_coverage()
        assert result.status == Status.PASS

    def test_warn_few_patterns(self, tmp_path, monkeypatch):
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "status_fingerprints.py").write_text('    ("fp_1",\n    ("fp_2",\n')
        monkeypatch.setattr("abc_audit.PROJECT_ROOT", tmp_path)
        result = check_r11_fingerprint_coverage()
        assert result.status == Status.WARN


# ---------------------------------------------------------------------------
# R.12: Reproducibility instructions
# ---------------------------------------------------------------------------

class TestR12ReproInstructions:
    def test_pass(self, tmp_path, monkeypatch):
        (tmp_path / "CLAUDE.md").write_text("## Running Tasks\nUse ./configs/...\n")
        monkeypatch.setattr("abc_audit.PROJECT_ROOT", tmp_path)
        result = check_r12_repro_instructions()
        assert result.status == Status.PASS

    def test_warn_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("abc_audit.PROJECT_ROOT", tmp_path)
        result = check_r12_repro_instructions()
        assert result.status == Status.WARN


# ---------------------------------------------------------------------------
# R.13: MANIFEST.json
# ---------------------------------------------------------------------------

class TestR13Manifest:
    def test_pass(self, tmp_path, monkeypatch):
        runs = tmp_path / "runs" / "official"
        runs.mkdir(parents=True)
        (runs / "MANIFEST.json").write_text('[{"task": "t1"}]')
        monkeypatch.setattr("abc_audit.RUNS_DIR", runs)
        result = check_r13_manifest()
        assert result.status == Status.PASS

    def test_warn_missing(self, tmp_path, monkeypatch):
        runs = tmp_path / "runs" / "official"
        runs.mkdir(parents=True)
        monkeypatch.setattr("abc_audit.RUNS_DIR", runs)
        result = check_r13_manifest()
        assert result.status == Status.WARN


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_discover_tasks(self, task_tree, monkeypatch):
        tmp_path, _, _ = task_tree
        monkeypatch.setattr("abc_audit.BENCHMARKS_DIR", tmp_path / "benchmarks")
        tasks = discover_tasks("ccb_test")
        assert len(tasks) == 2

    def test_discover_all_suites(self, task_tree, monkeypatch):
        tmp_path, _, _ = task_tree
        monkeypatch.setattr("abc_audit.BENCHMARKS_DIR", tmp_path / "benchmarks")
        suites = discover_all_suites()
        assert "ccb_test" in suites


# ---------------------------------------------------------------------------
# Integration: audit_suite
# ---------------------------------------------------------------------------

class TestAuditSuite:
    def test_audit_produces_report(self, task_tree, monkeypatch):
        tmp_path, _, _ = task_tree
        monkeypatch.setattr("abc_audit.BENCHMARKS_DIR", tmp_path / "benchmarks")
        monkeypatch.setattr("abc_audit.PROJECT_ROOT", tmp_path)
        monkeypatch.setattr("abc_audit.RUNS_DIR", tmp_path / "runs" / "official")
        monkeypatch.setattr("abc_audit.SELECTED_TASKS_PATH", tmp_path / "nope.json")
        report = audit_suite("ccb_test")
        assert report.target == "ccb_test"
        assert len(report.results) > 0
        assert report.grade is not None

    def test_audit_dimension_filter(self, task_tree, monkeypatch):
        tmp_path, _, _ = task_tree
        monkeypatch.setattr("abc_audit.BENCHMARKS_DIR", tmp_path / "benchmarks")
        monkeypatch.setattr("abc_audit.PROJECT_ROOT", tmp_path)
        monkeypatch.setattr("abc_audit.RUNS_DIR", tmp_path / "runs" / "official")
        monkeypatch.setattr("abc_audit.SELECTED_TASKS_PATH", tmp_path / "nope.json")
        report = audit_suite("ccb_test", dimension=Dimension.TASK_VALIDITY)
        # Should only have task_validity criteria
        from abc_criteria import CRITERIA_BY_ID
        for r in report.results:
            crit = CRITERIA_BY_ID.get(r.criterion_id)
            if crit:
                assert crit.dimension == Dimension.TASK_VALIDITY

    def test_audit_json_output(self, task_tree, monkeypatch):
        tmp_path, _, _ = task_tree
        monkeypatch.setattr("abc_audit.BENCHMARKS_DIR", tmp_path / "benchmarks")
        monkeypatch.setattr("abc_audit.PROJECT_ROOT", tmp_path)
        monkeypatch.setattr("abc_audit.RUNS_DIR", tmp_path / "runs" / "official")
        monkeypatch.setattr("abc_audit.SELECTED_TASKS_PATH", tmp_path / "nope.json")
        report = audit_suite("ccb_test")
        j = report.to_json()
        parsed = json.loads(j)
        assert parsed["target"] == "ccb_test"
        assert "results" in parsed
        assert "grade" in parsed

    def test_audit_table_output(self, task_tree, monkeypatch):
        tmp_path, _, _ = task_tree
        monkeypatch.setattr("abc_audit.BENCHMARKS_DIR", tmp_path / "benchmarks")
        monkeypatch.setattr("abc_audit.PROJECT_ROOT", tmp_path)
        monkeypatch.setattr("abc_audit.RUNS_DIR", tmp_path / "runs" / "official")
        monkeypatch.setattr("abc_audit.SELECTED_TASKS_PATH", tmp_path / "nope.json")
        report = audit_suite("ccb_test")
        table = report.to_table()
        assert "ccb_test" in table
        assert "Grade:" in table


# ---------------------------------------------------------------------------
# Check coverage: ensure all 32 criteria are handled
# ---------------------------------------------------------------------------

class TestCheckCoverage:
    def test_all_criteria_mapped(self):
        from abc_criteria import ALL_CRITERIA
        handled = set(TASK_CHECKS) | set(SUITE_CHECKS) | set(PROJECT_CHECKS) | SKIP_CHECKS
        # Also include delegated criteria
        delegated = {c.id for c in ALL_CRITERIA if c.delegated_to}
        covered = handled | delegated

        all_ids = {c.id for c in ALL_CRITERIA}
        missing = all_ids - covered
        assert not missing, f"Criteria not handled: {missing}"
