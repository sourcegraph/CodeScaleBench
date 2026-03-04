#!/usr/bin/env python3
"""ABC Framework data model: 32 criteria, report structures, grading.

Based on "Establishing Best Practices for Building Rigorous Agentic Benchmarks"
(arxiv 2507.02825). Criteria organized across Task Validity, Outcome Validity,
and Reporting dimensions.
"""

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Dimension(str, Enum):
    TASK_VALIDITY = "task_validity"
    OUTCOME_VALIDITY = "outcome_validity"
    REPORTING = "reporting"


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    IMPORTANT = "IMPORTANT"
    RECOMMENDED = "RECOMMENDED"


class Automation(str, Enum):
    AUTOMATED = "automated"
    SEMI_AUTOMATED = "semi_automated"
    MANUAL = "manual"


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"
    SKIP = "SKIP"
    ERROR = "ERROR"


class Grade(str, Enum):
    A = "A"  # All pass
    B = "B"  # All critical + >80% important
    C = "C"  # All critical + <80% important
    D = "D"  # Any critical fail
    F = "F"  # Multiple critical fail


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ABCCriterion:
    """One of 32 ABC quality criteria."""
    id: str
    dimension: Dimension
    title: str
    description: str
    severity: Severity
    automation: Automation
    applies_to: list[str] = field(default_factory=lambda: ["all"])
    delegated_to: Optional[str] = None

    def applies_to_suite(self, suite: str) -> bool:
        """Check if this criterion applies to a given benchmark suite."""
        if "all" in self.applies_to:
            return True
        return suite in self.applies_to


@dataclass
class CriterionResult:
    """Result of evaluating one criterion against a target."""
    criterion_id: str
    status: Status
    evidence: str = ""
    remediation: str = ""
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class AuditReport:
    """Full audit report for a benchmark suite or task."""
    target: str
    results: list[CriterionResult] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    overall_pass: bool = True
    grade: Grade = Grade.A

    def compute_grade(self) -> None:
        """Compute grade from results and update summary."""
        total = len(self.results)
        by_status = {s: 0 for s in Status}
        critical_fail = 0
        important_fail = 0
        important_total = 0

        criteria_map = {c.id: c for c in ALL_CRITERIA}

        for r in self.results:
            by_status[r.status] = by_status.get(r.status, 0) + 1
            criterion = criteria_map.get(r.criterion_id)
            if criterion is None:
                continue
            if criterion.severity == Severity.CRITICAL and r.status == Status.FAIL:
                critical_fail += 1
            if criterion.severity == Severity.IMPORTANT:
                important_total += 1
                if r.status == Status.FAIL:
                    important_fail += 1

        important_pass_rate = (
            (important_total - important_fail) / important_total
            if important_total > 0
            else 1.0
        )

        if critical_fail >= 2:
            self.grade = Grade.F
        elif critical_fail == 1:
            self.grade = Grade.D
        elif important_pass_rate < 0.8:
            self.grade = Grade.C
        elif important_fail > 0:
            self.grade = Grade.B
        else:
            self.grade = Grade.A

        self.overall_pass = critical_fail == 0

        self.summary = {
            "total_criteria": total,
            "pass": by_status.get(Status.PASS, 0),
            "fail": by_status.get(Status.FAIL, 0),
            "warn": by_status.get(Status.WARN, 0),
            "skip": by_status.get(Status.SKIP, 0),
            "error": by_status.get(Status.ERROR, 0),
            "critical_failures": critical_fail,
            "important_pass_rate": round(important_pass_rate, 2),
            "grade": self.grade.value,
        }

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "overall_pass": self.overall_pass,
            "grade": self.grade.value,
            "summary": self.summary,
            "results": [r.to_dict() for r in self.results],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def to_table(self) -> str:
        """Format as human-readable ASCII table."""
        lines = []
        lines.append(f"ABC Audit Report: {self.target}")
        lines.append(f"Grade: {self.grade.value}  |  Overall: {'PASS' if self.overall_pass else 'FAIL'}")
        lines.append("")

        if self.summary:
            lines.append(
                f"  Criteria: {self.summary.get('total_criteria', 0)}  "
                f"Pass: {self.summary.get('pass', 0)}  "
                f"Fail: {self.summary.get('fail', 0)}  "
                f"Warn: {self.summary.get('warn', 0)}  "
                f"Skip: {self.summary.get('skip', 0)}"
            )
            lines.append(
                f"  Critical failures: {self.summary.get('critical_failures', 0)}  "
                f"Important pass rate: {self.summary.get('important_pass_rate', 'N/A')}"
            )
            lines.append("")

        criteria_map = {c.id: c for c in ALL_CRITERIA}

        # Header
        lines.append(f"  {'ID':<6} {'Status':<6} {'Sev':<12} {'Title':<50}")
        lines.append(f"  {'─' * 6} {'─' * 6} {'─' * 12} {'─' * 50}")

        for r in self.results:
            criterion = criteria_map.get(r.criterion_id)
            sev = criterion.severity.value if criterion else "?"
            title = criterion.title[:50] if criterion else r.criterion_id
            lines.append(f"  {r.criterion_id:<6} {r.status.value:<6} {sev:<12} {title}")
            if r.status == Status.FAIL and r.evidence:
                # Indent evidence under failures
                for ev_line in r.evidence.split("\n")[:3]:
                    lines.append(f"         {ev_line[:80]}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# The 32 Criteria
# ---------------------------------------------------------------------------

# Suites that have local Dockerfiles (not Harbor-registry only)
_HAS_DOCKERFILE = [
    "ccb_swebenchpro", "ccb_pytorch", "ccb_locobench", "ccb_repoqa",
    "ccb_k8s_docs", "ccb_crossrepo", "ccb_largerepo", "ccb_tac",
    "ccb_dibench", "ccb_sweperf", "ccb_codereview", "ccb_linuxflbench",
]

ALL_CRITERIA: list[ABCCriterion] = [
    # ── Task Validity ─────────────────────────────────────────────────
    ABCCriterion(
        id="T.1",
        dimension=Dimension.TASK_VALIDITY,
        title="Dockerfile pins versions (no :latest, pinned apt)",
        description="Dockerfiles must pin base image tags and package versions for reproducibility.",
        severity=Severity.CRITICAL,
        automation=Automation.AUTOMATED,
        applies_to=_HAS_DOCKERFILE,
    ),
    ABCCriterion(
        id="T.2",
        dimension=Dimension.TASK_VALIDITY,
        title="No unreachable external URLs in instruction.md",
        description="External URLs referenced in instructions should be reachable.",
        severity=Severity.IMPORTANT,
        automation=Automation.SEMI_AUTOMATED,
    ),
    ABCCriterion(
        id="T.3",
        dimension=Dimension.TASK_VALIDITY,
        title="No shared API keys in task.toml/Dockerfile",
        description="Tasks must not embed API keys, tokens, or credentials.",
        severity=Severity.IMPORTANT,
        automation=Automation.AUTOMATED,
    ),
    ABCCriterion(
        id="T.4",
        dimension=Dimension.TASK_VALIDITY,
        title="Git checkouts use exact SHA (not HEAD/latest)",
        description="Git clone/checkout commands in Dockerfiles must pin to exact commit SHAs.",
        severity=Severity.CRITICAL,
        automation=Automation.AUTOMATED,
        applies_to=_HAS_DOCKERFILE,
    ),
    ABCCriterion(
        id="T.5",
        dimension=Dimension.TASK_VALIDITY,
        title="instruction.md doesn't leak solution content",
        description="Instructions must not contain solution code or test answers.",
        severity=Severity.CRITICAL,
        automation=Automation.AUTOMATED,
    ),
    ABCCriterion(
        id="T.6",
        dimension=Dimension.TASK_VALIDITY,
        title="Dockerfile exists, deterministic base image",
        description="Each task must have a Dockerfile with a deterministic (pinned) base image.",
        severity=Severity.CRITICAL,
        automation=Automation.AUTOMATED,
        applies_to=_HAS_DOCKERFILE,
        delegated_to="validate_tasks_preflight.py",
    ),
    ABCCriterion(
        id="T.7",
        dimension=Dimension.TASK_VALIDITY,
        title="task.toml metadata matches selected_benchmark_tasks.json",
        description="Task metadata in task.toml should be consistent with the selection registry.",
        severity=Severity.IMPORTANT,
        automation=Automation.AUTOMATED,
        delegated_to="sync_task_metadata.py",
    ),
    ABCCriterion(
        id="T.8",
        dimension=Dimension.TASK_VALIDITY,
        title="Oracle/reference solution exists",
        description="Tasks should have a reference solution (solve.sh, expected.diff) for validation.",
        severity=Severity.RECOMMENDED,
        automation=Automation.AUTOMATED,
    ),
    ABCCriterion(
        id="T.9",
        dimension=Dimension.TASK_VALIDITY,
        title="No systematic verifier false-positive pattern",
        description="Run results should not show suspicious all-pass patterns indicating broken verifiers.",
        severity=Severity.RECOMMENDED,
        automation=Automation.SEMI_AUTOMATED,
    ),
    ABCCriterion(
        id="T.10",
        dimension=Dimension.TASK_VALIDITY,
        title="No shared mutable state between tasks",
        description="Tasks must be independently runnable without shared state.",
        severity=Severity.IMPORTANT,
        automation=Automation.MANUAL,
    ),

    # ── Outcome Validity ──────────────────────────────────────────────
    ABCCriterion(
        id="O.a",
        dimension=Dimension.OUTCOME_VALIDITY,
        title="Verifier handles equivalent solutions",
        description="Verifier should accept correct alternative solutions, not just exact matches.",
        severity=Severity.CRITICAL,
        automation=Automation.SEMI_AUTOMATED,
    ),
    ABCCriterion(
        id="O.b",
        dimension=Dimension.OUTCOME_VALIDITY,
        title="Verifier rejects negated/inverted solutions",
        description="Verifier should reject solutions that produce opposite behavior.",
        severity=Severity.IMPORTANT,
        automation=Automation.SEMI_AUTOMATED,
    ),
    ABCCriterion(
        id="O.c",
        dimension=Dimension.OUTCOME_VALIDITY,
        title="Empty/no-op solution gets reward=0",
        description="test.sh must have real assertions; empty solutions must score zero.",
        severity=Severity.CRITICAL,
        automation=Automation.AUTOMATED,
    ),
    ABCCriterion(
        id="O.d",
        dimension=Dimension.OUTCOME_VALIDITY,
        title="test.sh has error handling (set -e or traps)",
        description="Verification scripts must fail fast on errors.",
        severity=Severity.CRITICAL,
        automation=Automation.AUTOMATED,
    ),
    ABCCriterion(
        id="O.e",
        dimension=Dimension.OUTCOME_VALIDITY,
        title="test.sh covers multiple aspects (>1 assertion)",
        description="Verifier should test multiple aspects of the solution.",
        severity=Severity.IMPORTANT,
        automation=Automation.AUTOMATED,
    ),
    ABCCriterion(
        id="O.f",
        dimension=Dimension.OUTCOME_VALIDITY,
        title="Edge cases handled (partial solutions, wrong format)",
        description="Verifier should handle edge cases gracefully.",
        severity=Severity.RECOMMENDED,
        automation=Automation.SEMI_AUTOMATED,
    ),
    ABCCriterion(
        id="O.g",
        dimension=Dimension.OUTCOME_VALIDITY,
        title="test.sh is deterministic (no uncontrolled randomness)",
        description="Verification should not depend on random state.",
        severity=Severity.IMPORTANT,
        automation=Automation.SEMI_AUTOMATED,
    ),
    ABCCriterion(
        id="O.h",
        dimension=Dimension.OUTCOME_VALIDITY,
        title="reward.txt output format is consistent",
        description="test.sh must write reward to /logs/verifier/reward.txt.",
        severity=Severity.IMPORTANT,
        automation=Automation.AUTOMATED,
    ),
    ABCCriterion(
        id="O.i",
        dimension=Dimension.OUTCOME_VALIDITY,
        title="Verifier supports partial credit (0.0-1.0 range)",
        description="Verifier should support fractional reward, not just binary pass/fail.",
        severity=Severity.RECOMMENDED,
        automation=Automation.AUTOMATED,
    ),

    # ── Reporting ─────────────────────────────────────────────────────
    ABCCriterion(
        id="R.1",
        dimension=Dimension.REPORTING,
        title="All tasks have instruction.md + test.sh",
        description="Every task must have both an instruction file and a verification script.",
        severity=Severity.CRITICAL,
        automation=Automation.AUTOMATED,
        delegated_to="validate_tasks_preflight.py",
    ),
    ABCCriterion(
        id="R.2",
        dimension=Dimension.REPORTING,
        title="No MCP/Sourcegraph contamination in instruction.md",
        description="Baseline instructions must not reference MCP, Sourcegraph, or Deep Search.",
        severity=Severity.CRITICAL,
        automation=Automation.AUTOMATED,
    ),
    ABCCriterion(
        id="R.3",
        dimension=Dimension.REPORTING,
        title="Benchmark describes what it measures",
        description="Benchmark suite should have documentation (README) describing its purpose.",
        severity=Severity.IMPORTANT,
        automation=Automation.AUTOMATED,
    ),
    ABCCriterion(
        id="R.4",
        dimension=Dimension.REPORTING,
        title="sdlc_phase populated in selected_benchmark_tasks.json",
        description="Each task in the selection registry should have its SDLC phase documented.",
        severity=Severity.IMPORTANT,
        automation=Automation.AUTOMATED,
    ),
    ABCCriterion(
        id="R.5",
        dimension=Dimension.REPORTING,
        title="ERROR_CATALOG.md covers all fingerprinted errors",
        description="The error catalog should document all known error fingerprints.",
        severity=Severity.RECOMMENDED,
        automation=Automation.AUTOMATED,
    ),
    ABCCriterion(
        id="R.6",
        dimension=Dimension.REPORTING,
        title="Multiple config results available for comparison",
        description="At least 2 configurations should have run results for meaningful comparison.",
        severity=Severity.IMPORTANT,
        automation=Automation.SEMI_AUTOMATED,
    ),
    ABCCriterion(
        id="R.7",
        dimension=Dimension.REPORTING,
        title="Baseline config results exist",
        description="Baseline (no-MCP) results must exist for each benchmark.",
        severity=Severity.CRITICAL,
        automation=Automation.AUTOMATED,
        delegated_to="aggregate_status.py",
    ),
    ABCCriterion(
        id="R.8",
        dimension=Dimension.REPORTING,
        title="TASK_SELECTION.md documents methodology",
        description="Task selection methodology should be documented.",
        severity=Severity.IMPORTANT,
        automation=Automation.AUTOMATED,
    ),
    ABCCriterion(
        id="R.9",
        dimension=Dimension.REPORTING,
        title="Difficulty distribution is documented and balanced",
        description="Tasks should span multiple difficulty levels with documented distribution.",
        severity=Severity.IMPORTANT,
        automation=Automation.AUTOMATED,
    ),
    ABCCriterion(
        id="R.10",
        dimension=Dimension.REPORTING,
        title="Token/cost data captured per run",
        description="Run results should include token usage for cost analysis.",
        severity=Severity.RECOMMENDED,
        automation=Automation.AUTOMATED,
    ),
    ABCCriterion(
        id="R.11",
        dimension=Dimension.REPORTING,
        title="Error fingerprinting covers >=10 patterns",
        description="Error classification should cover a sufficient range of failure modes.",
        severity=Severity.RECOMMENDED,
        automation=Automation.AUTOMATED,
    ),
    ABCCriterion(
        id="R.12",
        dimension=Dimension.REPORTING,
        title="Reproducibility instructions in CLAUDE.md",
        description="Project documentation should explain how to reproduce benchmark runs.",
        severity=Severity.IMPORTANT,
        automation=Automation.AUTOMATED,
    ),
    ABCCriterion(
        id="R.13",
        dimension=Dimension.REPORTING,
        title="MANIFEST.json tracks run results",
        description="A manifest file should track all run results for traceability.",
        severity=Severity.RECOMMENDED,
        automation=Automation.AUTOMATED,
    ),
]

# Lookup helpers
CRITERIA_BY_ID: dict[str, ABCCriterion] = {c.id: c for c in ALL_CRITERIA}
CRITERIA_BY_DIMENSION: dict[Dimension, list[ABCCriterion]] = {}
for _c in ALL_CRITERIA:
    CRITERIA_BY_DIMENSION.setdefault(_c.dimension, []).append(_c)


def get_criteria_for_suite(suite: str) -> list[ABCCriterion]:
    """Return criteria applicable to a given benchmark suite."""
    return [c for c in ALL_CRITERIA if c.applies_to_suite(suite)]


def get_criteria_by_dimension(dimension: Dimension) -> list[ABCCriterion]:
    """Return all criteria for a given dimension."""
    return CRITERIA_BY_DIMENSION.get(dimension, [])
