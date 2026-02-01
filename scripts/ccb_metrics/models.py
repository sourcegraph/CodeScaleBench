"""Data models for CodeContextBench evaluation metrics.

Stdlib only: dataclasses, json, pathlib, typing, datetime, statistics.
Compatible with Python 3.10+.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class TaskMetrics:
    """Per-task metrics extracted from a Harbor run."""

    task_id: str
    benchmark: str
    config_name: str

    # Scoring
    reward: Optional[float] = None
    partial_score: Optional[float] = None
    status: str = "unknown"  # passed / failed / error

    # Timing (seconds)
    wall_clock_seconds: Optional[float] = None
    agent_execution_seconds: Optional[float] = None
    environment_setup_seconds: Optional[float] = None
    verifier_seconds: Optional[float] = None

    # Token usage
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_creation_tokens: Optional[int] = None
    cache_read_tokens: Optional[int] = None

    # Cost
    cost_usd: Optional[float] = None

    # Tool usage
    tool_calls_total: Optional[int] = None
    tool_calls_mcp: Optional[int] = None
    tool_calls_local: Optional[int] = None
    tool_calls_by_name: Optional[dict[str, int]] = None
    mcp_ratio: Optional[float] = None

    # Code changes
    files_modified: Optional[int] = None
    lines_added: Optional[int] = None
    lines_removed: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> TaskMetrics:
        # Filter to only known fields
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in data.items() if k in known})


def _safe_mean(values: list[float | int]) -> Optional[float]:
    """Return mean of non-None values, or None if empty."""
    filtered = [v for v in values if v is not None]
    if not filtered:
        return None
    return statistics.mean(filtered)


@dataclass
class RunMetrics:
    """Aggregate metrics for one (benchmark, config) run."""

    run_id: str
    benchmark: str
    config_name: str
    model: str
    timestamp: str
    task_count: int
    tasks: list[TaskMetrics] = field(default_factory=list)
    harness_config: Optional[dict] = None

    # --- computed properties ---

    @property
    def mean_reward(self) -> Optional[float]:
        return _safe_mean([t.reward for t in self.tasks])

    @property
    def mean_partial_score(self) -> Optional[float]:
        return _safe_mean([t.partial_score for t in self.tasks])

    @property
    def pass_rate(self) -> Optional[float]:
        scored = [t for t in self.tasks if t.status in ("passed", "failed")]
        if not scored:
            return None
        return sum(1 for t in scored if t.status == "passed") / len(scored)

    @property
    def mean_tokens(self) -> Optional[float]:
        totals = []
        for t in self.tasks:
            if t.input_tokens is not None and t.output_tokens is not None:
                totals.append(t.input_tokens + t.output_tokens)
        return _safe_mean(totals) if totals else None

    @property
    def mean_wall_clock(self) -> Optional[float]:
        return _safe_mean([t.wall_clock_seconds for t in self.tasks])

    @property
    def mean_mcp_ratio(self) -> Optional[float]:
        return _safe_mean([t.mcp_ratio for t in self.tasks])

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "benchmark": self.benchmark,
            "config_name": self.config_name,
            "model": self.model,
            "timestamp": self.timestamp,
            "task_count": self.task_count,
            "tasks": [t.to_dict() for t in self.tasks],
            "harness_config": self.harness_config,
            "mean_reward": self.mean_reward,
            "mean_partial_score": self.mean_partial_score,
            "pass_rate": self.pass_rate,
            "mean_tokens": self.mean_tokens,
            "mean_wall_clock": self.mean_wall_clock,
            "mean_mcp_ratio": self.mean_mcp_ratio,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RunMetrics:
        tasks_data = data.pop("tasks", [])
        # Remove computed properties that may be in serialized form
        for key in ("mean_reward", "mean_partial_score", "pass_rate",
                     "mean_tokens", "mean_wall_clock", "mean_mcp_ratio"):
            data.pop(key, None)
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        run = cls(**filtered)
        run.tasks = [TaskMetrics.from_dict(td) for td in tasks_data]
        return run


@dataclass
class EvalReport:
    """Top-level evaluation report aggregating all runs."""

    report_id: str
    generated_at: str
    runs: list[RunMetrics] = field(default_factory=list)

    def configs(self) -> list[str]:
        """Return unique config names across all runs."""
        return sorted({r.config_name for r in self.runs})

    def benchmarks(self) -> list[str]:
        """Return unique benchmark names across all runs."""
        return sorted({r.benchmark for r in self.runs})

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "runs": [r.to_dict() for r in self.runs],
        }

    @classmethod
    def from_dict(cls, data: dict) -> EvalReport:
        runs_data = data.pop("runs", [])
        report = cls(
            report_id=data["report_id"],
            generated_at=data["generated_at"],
        )
        report.runs = [RunMetrics.from_dict(rd) for rd in runs_data]
        return report

    def to_json(self, path: str | Path) -> None:
        """Write the full report to a JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")
