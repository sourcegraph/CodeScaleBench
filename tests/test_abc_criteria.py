#!/usr/bin/env python3
"""Tests for scripts/abc_criteria.py — ABC Framework data model."""

import json
import sys
from pathlib import Path


# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from abc_criteria import (
    ABCCriterion,
    ALL_CRITERIA,
    AuditReport,
    Automation,
    CRITERIA_BY_DIMENSION,
    CRITERIA_BY_ID,
    CriterionResult,
    Dimension,
    Grade,
    Severity,
    Status,
    get_criteria_by_dimension,
    get_criteria_for_suite,
)


# ---------------------------------------------------------------------------
# ABCCriterion
# ---------------------------------------------------------------------------

class TestABCCriterion:
    def test_applies_to_all(self):
        c = ABCCriterion(
            id="X.1", dimension=Dimension.TASK_VALIDITY, title="Test",
            description="desc", severity=Severity.CRITICAL,
            automation=Automation.AUTOMATED,
        )
        assert c.applies_to_suite("ccb_pytorch")
        assert c.applies_to_suite("anything")

    def test_applies_to_specific_suites(self):
        c = ABCCriterion(
            id="X.2", dimension=Dimension.TASK_VALIDITY, title="Test",
            description="desc", severity=Severity.CRITICAL,
            automation=Automation.AUTOMATED,
            applies_to=["ccb_pytorch", "ccb_k8s_docs"],
        )
        assert c.applies_to_suite("ccb_pytorch")
        assert c.applies_to_suite("ccb_k8s_docs")
        assert not c.applies_to_suite("ccb_dibench")

    def test_default_applies_to_is_all(self):
        c = ABCCriterion(
            id="X.3", dimension=Dimension.REPORTING, title="T",
            description="d", severity=Severity.RECOMMENDED,
            automation=Automation.MANUAL,
        )
        assert c.applies_to == ["all"]


# ---------------------------------------------------------------------------
# CriterionResult
# ---------------------------------------------------------------------------

class TestCriterionResult:
    def test_to_dict(self):
        r = CriterionResult(
            criterion_id="T.1", status=Status.PASS,
            evidence="All Dockerfiles pin versions",
        )
        d = r.to_dict()
        assert d["criterion_id"] == "T.1"
        assert d["status"] == "PASS"
        assert d["evidence"] == "All Dockerfiles pin versions"
        assert d["details"] == {}

    def test_to_dict_with_details(self):
        r = CriterionResult(
            criterion_id="O.c", status=Status.FAIL,
            evidence="test.sh has no assertions",
            remediation="Add assert/test commands to test.sh",
            details={"tasks_failing": ["task-001", "task-002"]},
        )
        d = r.to_dict()
        assert d["status"] == "FAIL"
        assert d["remediation"] == "Add assert/test commands to test.sh"
        assert d["details"]["tasks_failing"] == ["task-001", "task-002"]

    def test_default_fields(self):
        r = CriterionResult(criterion_id="R.1", status=Status.SKIP)
        assert r.evidence == ""
        assert r.remediation == ""
        assert r.details == {}


# ---------------------------------------------------------------------------
# ALL_CRITERIA registry
# ---------------------------------------------------------------------------

class TestCriteriaRegistry:
    def test_exactly_32_criteria(self):
        assert len(ALL_CRITERIA) == 32

    def test_unique_ids(self):
        ids = [c.id for c in ALL_CRITERIA]
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {[i for i in ids if ids.count(i) > 1]}"

    def test_id_format(self):
        """IDs must be T.N, O.x, or R.N format."""
        for c in ALL_CRITERIA:
            assert c.id[0] in ("T", "O", "R"), f"Bad prefix: {c.id}"
            assert c.id[1] == ".", f"Missing dot: {c.id}"

    def test_dimensions_covered(self):
        dims = {c.dimension for c in ALL_CRITERIA}
        assert Dimension.TASK_VALIDITY in dims
        assert Dimension.OUTCOME_VALIDITY in dims
        assert Dimension.REPORTING in dims

    def test_task_validity_count(self):
        tv = [c for c in ALL_CRITERIA if c.dimension == Dimension.TASK_VALIDITY]
        assert len(tv) == 10

    def test_outcome_validity_count(self):
        ov = [c for c in ALL_CRITERIA if c.dimension == Dimension.OUTCOME_VALIDITY]
        assert len(ov) == 9

    def test_reporting_count(self):
        rp = [c for c in ALL_CRITERIA if c.dimension == Dimension.REPORTING]
        assert len(rp) == 13

    def test_criteria_by_id_lookup(self):
        assert "T.1" in CRITERIA_BY_ID
        assert "O.a" in CRITERIA_BY_ID
        assert "R.13" in CRITERIA_BY_ID
        assert CRITERIA_BY_ID["T.1"].title == "Dockerfile pins versions (no :latest, pinned apt)"

    def test_criteria_by_dimension(self):
        for dim in Dimension:
            assert dim in CRITERIA_BY_DIMENSION
            assert len(CRITERIA_BY_DIMENSION[dim]) > 0

    def test_all_severities_used(self):
        severities = {c.severity for c in ALL_CRITERIA}
        assert Severity.CRITICAL in severities
        assert Severity.IMPORTANT in severities
        assert Severity.RECOMMENDED in severities

    def test_all_automation_levels_used(self):
        autos = {c.automation for c in ALL_CRITERIA}
        assert Automation.AUTOMATED in autos
        assert Automation.SEMI_AUTOMATED in autos
        assert Automation.MANUAL in autos

    def test_delegated_criteria_exist(self):
        delegated = [c for c in ALL_CRITERIA if c.delegated_to is not None]
        assert len(delegated) >= 3
        delegates = {c.delegated_to for c in delegated}
        assert "validate_tasks_preflight.py" in delegates
        assert "sync_task_metadata.py" in delegates
        assert "aggregate_status.py" in delegates


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_get_criteria_for_suite_all(self):
        result = get_criteria_for_suite("ccb_pytorch")
        # Should include "all" criteria plus pytorch-specific ones
        assert len(result) >= 20  # At minimum, all non-restricted criteria

    def test_get_criteria_for_suite_excludes(self):
        """DependEval (ccb_dependeval) should skip Dockerfile checks."""
        result = get_criteria_for_suite("ccb_dependeval")
        ids = {c.id for c in result}
        # T.1, T.4, T.6 have applies_to restricted to _HAS_DOCKERFILE
        assert "T.1" not in ids
        assert "T.4" not in ids
        assert "T.6" not in ids
        # But universal criteria should still be there
        assert "T.5" in ids
        assert "R.1" in ids

    def test_get_criteria_by_dimension(self):
        tv = get_criteria_by_dimension(Dimension.TASK_VALIDITY)
        assert len(tv) == 10
        assert all(c.dimension == Dimension.TASK_VALIDITY for c in tv)


# ---------------------------------------------------------------------------
# AuditReport
# ---------------------------------------------------------------------------

class TestAuditReport:
    def _make_report(self, results: list[CriterionResult]) -> AuditReport:
        report = AuditReport(target="ccb_test", results=results)
        report.compute_grade()
        return report

    def test_grade_a_all_pass(self):
        results = [
            CriterionResult(criterion_id=c.id, status=Status.PASS)
            for c in ALL_CRITERIA
        ]
        report = self._make_report(results)
        assert report.grade == Grade.A
        assert report.overall_pass is True

    def test_grade_d_one_critical_fail(self):
        results = []
        for c in ALL_CRITERIA:
            if c.id == "T.1" and c.severity == Severity.CRITICAL:
                results.append(CriterionResult(criterion_id=c.id, status=Status.FAIL))
            else:
                results.append(CriterionResult(criterion_id=c.id, status=Status.PASS))
        report = self._make_report(results)
        assert report.grade == Grade.D
        assert report.overall_pass is False

    def test_grade_f_multiple_critical_fail(self):
        results = []
        critical_count = 0
        for c in ALL_CRITERIA:
            if c.severity == Severity.CRITICAL and critical_count < 2:
                results.append(CriterionResult(criterion_id=c.id, status=Status.FAIL))
                critical_count += 1
            else:
                results.append(CriterionResult(criterion_id=c.id, status=Status.PASS))
        report = self._make_report(results)
        assert report.grade == Grade.F
        assert report.overall_pass is False

    def test_grade_b_important_fails(self):
        """All critical pass but one IMPORTANT fails -> B (if pass rate >80%)."""
        results = []
        important_failed = False
        for c in ALL_CRITERIA:
            if c.severity == Severity.IMPORTANT and not important_failed:
                results.append(CriterionResult(criterion_id=c.id, status=Status.FAIL))
                important_failed = True
            else:
                results.append(CriterionResult(criterion_id=c.id, status=Status.PASS))
        report = self._make_report(results)
        # 1 fail out of many important -> >80% pass rate -> Grade B
        assert report.grade == Grade.B
        assert report.overall_pass is True

    def test_grade_c_many_important_fails(self):
        """All critical pass but many IMPORTANT fail (>20%) -> C."""
        results = []
        important_criteria = [c for c in ALL_CRITERIA if c.severity == Severity.IMPORTANT]
        fail_count = len(important_criteria)  # Fail all important
        for c in ALL_CRITERIA:
            if c.severity == Severity.IMPORTANT:
                results.append(CriterionResult(criterion_id=c.id, status=Status.FAIL))
            else:
                results.append(CriterionResult(criterion_id=c.id, status=Status.PASS))
        report = self._make_report(results)
        assert report.grade == Grade.C
        assert report.overall_pass is True  # No critical failures

    def test_summary_fields(self):
        results = [
            CriterionResult(criterion_id="T.1", status=Status.PASS),
            CriterionResult(criterion_id="T.2", status=Status.FAIL),
            CriterionResult(criterion_id="T.3", status=Status.SKIP),
        ]
        report = AuditReport(target="test", results=results)
        report.compute_grade()
        s = report.summary
        assert s["total_criteria"] == 3
        assert s["pass"] == 1
        assert s["fail"] == 1
        assert s["skip"] == 1
        assert "grade" in s

    def test_to_dict(self):
        results = [CriterionResult(criterion_id="T.1", status=Status.PASS)]
        report = AuditReport(target="test", results=results)
        report.compute_grade()
        d = report.to_dict()
        assert d["target"] == "test"
        assert isinstance(d["results"], list)
        assert d["results"][0]["status"] == "PASS"

    def test_to_json_valid(self):
        results = [CriterionResult(criterion_id="T.1", status=Status.PASS)]
        report = AuditReport(target="test", results=results)
        report.compute_grade()
        j = report.to_json()
        parsed = json.loads(j)
        assert parsed["target"] == "test"

    def test_to_table_contains_header(self):
        results = [
            CriterionResult(criterion_id="T.1", status=Status.PASS),
            CriterionResult(criterion_id="R.2", status=Status.FAIL, evidence="Found MCP reference"),
        ]
        report = AuditReport(target="ccb_repoqa", results=results)
        report.compute_grade()
        table = report.to_table()
        assert "ccb_repoqa" in table
        assert "T.1" in table
        assert "PASS" in table
        assert "R.2" in table
        assert "FAIL" in table
        assert "Found MCP reference" in table

    def test_empty_report(self):
        report = AuditReport(target="empty")
        report.compute_grade()
        assert report.grade == Grade.A
        assert report.overall_pass is True
        assert report.summary["total_criteria"] == 0
