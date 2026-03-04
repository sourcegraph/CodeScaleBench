"""Data models for the CCB LLM Judge.

Stdlib only: dataclasses, typing, json, datetime.
Compatible with Python 3.10+.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class JudgeInput:
    """Input data bundle for evaluating a single task."""

    task_id: str
    task_description: str
    code_changes: str
    tool_calls: str
    verifier_reward: float
    oracle_ground_truth: str
    oracle_expected_approach: str
    oracle_evaluation_criteria: list[str] = field(default_factory=list)
    oracle_context_files: list[str] = field(default_factory=list)
    mcp_tools_used: list[str] = field(default_factory=list)


@dataclass
class OracleBundle:
    """Ground-truth oracle data discovered for a task."""

    ground_truth_text: str = ""
    expected_approach: str = ""
    evaluation_criteria: list[str] = field(default_factory=list)
    context_files: list[str] = field(default_factory=list)
    confidence: str = "low"  # high | medium | low


@dataclass
class JudgeResult:
    """Output from the LLM judge for a single task.

    to_dict() produces JSON-serializable output matching
    schemas/judge_result.schema.json.
    """

    task_id: str
    benchmark: str
    config: str
    judge_score: float
    dimension_scores: dict[str, float] = field(default_factory=dict)
    oracle_confidence: str = "low"
    model: str = ""
    temperature: float = 0.0
    rounds: int = 1
    vote_distribution: dict = field(default_factory=dict)
    judged_at: str = ""
    provenance: dict = field(default_factory=dict)
    # Hybrid evaluation fields (populated when criteria.json is present)
    criteria_scores: dict = field(default_factory=dict)
    rubric_score: float = 0.0
    hybrid_composite: Optional[float] = None
    verifier_weight: float = 0.6

    def to_dict(self) -> dict:
        """Produce JSON-serializable output matching judge_result.schema.json."""
        result: dict = {
            "task_id": self.task_id,
            "benchmark": self.benchmark,
            "config": self.config,
            "judge_score": self.judge_score,
            "judge_model": self.model,
            "judged_at": self.judged_at or datetime.now(timezone.utc).isoformat(),
            "rubric": self.dimension_scores,
            "rationale": self.provenance.get("rationale", ""),
            "oracle_confidence": self.oracle_confidence,
            "temperature": self.temperature,
            "rounds": self.rounds,
            "vote_distribution": self.vote_distribution,
            "provenance": self.provenance,
        }
        # Include hybrid fields only when criteria scoring was performed
        if self.criteria_scores:
            result["criteria_scores"] = self.criteria_scores
            result["rubric_score"] = self.rubric_score
        if self.hybrid_composite is not None:
            result["hybrid_composite"] = self.hybrid_composite
            result["verifier_weight"] = self.verifier_weight
        return result


# ---- Helpers ----

_SCORE_MAP: dict[str, float] = {
    "pass": 1.0,
    "passed": 1.0,
    "partial": 0.5,
    "fail": 0.0,
    "failed": 0.0,
    "1.0": 1.0,
    "1": 1.0,
    "0.5": 0.5,
    "0.0": 0.0,
    "0": 0.0,
}


def normalize_score(value: str | float | int) -> float:
    """Map string/numeric score labels to float values.

    >>> normalize_score("pass")
    1.0
    >>> normalize_score("partial")
    0.5
    >>> normalize_score("fail")
    0.0
    >>> normalize_score("1.0")
    1.0
    >>> normalize_score(0.5)
    0.5
    >>> normalize_score("garbage")
    0.0
    """
    if isinstance(value, (int, float)):
        return float(value)
    key = str(value).strip().lower()
    return _SCORE_MAP.get(key, 0.0)
