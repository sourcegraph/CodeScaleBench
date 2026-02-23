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

    # LLM Judge (optional — separate from verifier reward)
    judge_score: Optional[float] = None
    judge_rubric: Optional[dict[str, float]] = None
    judge_model: Optional[str] = None
    oracle_confidence: Optional[str] = None  # high / medium / low

    # Task selection metadata (from selected_benchmark_tasks.json)
    sdlc_phase: Optional[str] = None
    language: Optional[str] = None
    category: Optional[str] = None
    difficulty: Optional[str] = None
    mcp_benefit_score: Optional[float] = None
    mcp_benefit_breakdown: Optional[dict[str, float]] = None
    repo: Optional[str] = None
    task_context_length: Optional[int] = None
    task_files_count: Optional[int] = None

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

    # Search patterns
    search_queries: Optional[list[dict]] = None
    search_calls_keyword: Optional[int] = None
    search_calls_nls: Optional[int] = None
    search_calls_deepsearch: Optional[int] = None
    deepsearch_keyword_ratio: Optional[float] = None
    search_strategy_type: Optional[str] = None  # keyword_only | nls_focused | deepsearch_heavy | mixed

    # Code changes
    files_modified: Optional[int] = None
    lines_added: Optional[int] = None
    lines_removed: Optional[int] = None

    # Derived efficiency
    input_output_ratio: Optional[float] = None
    cache_hit_rate: Optional[float] = None

    # Agent timeout flag (verifier still scored partial work)
    timed_out: bool = False

    # Tier 1: error & environment
    error_fingerprint: Optional[dict] = None
    verifier_test_summary: Optional[dict] = None
    agent_return_code: Optional[int] = None
    mcp_config_present: Optional[bool] = None
    mcp_servers: Optional[list[str]] = None
    instruction_length_chars: Optional[int] = None

    # Tier 2: conversation analysis
    conversation_turns: Optional[int] = None
    tool_errors_total: Optional[int] = None
    tool_errors_by_name: Optional[dict[str, int]] = None
    backtrack_count: Optional[int] = None
    mcp_latency_p50_ms: Optional[float] = None
    mcp_latency_p95_ms: Optional[float] = None
    context_window_peak_pct: Optional[float] = None

    # Time-to-relevant/context metrics (requires ground truth files)
    ttfr: Optional[float] = None
    ttfr_step: Optional[int] = None
    tt_all_r: Optional[float] = None
    n_steps_to_first: Optional[int] = None
    tokens_before_first_relevant: Optional[int] = None
    cost_before_first_relevant: Optional[float] = None
    output_tokens_before_first_relevant: Optional[int] = None
    agent_time_to_first_relevant: Optional[float] = None

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
    def mean_judge_score(self) -> Optional[float]:
        return _safe_mean([t.judge_score for t in self.tasks])

    @property
    def judge_coverage(self) -> Optional[float]:
        if not self.tasks:
            return None
        judged = sum(1 for t in self.tasks if t.judge_score is not None)
        return judged / len(self.tasks)

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
    def mean_agent_execution(self) -> Optional[float]:
        return _safe_mean([t.agent_execution_seconds for t in self.tasks])

    @property
    def mean_verifier(self) -> Optional[float]:
        return _safe_mean([t.verifier_seconds for t in self.tasks])

    @property
    def mean_mcp_ratio(self) -> Optional[float]:
        return _safe_mean([t.mcp_ratio for t in self.tasks])

    @property
    def mean_deepsearch_keyword_ratio(self) -> Optional[float]:
        return _safe_mean([t.deepsearch_keyword_ratio for t in self.tasks])

    @property
    def mean_input_output_ratio(self) -> Optional[float]:
        return _safe_mean([t.input_output_ratio for t in self.tasks])

    @property
    def mean_cache_hit_rate(self) -> Optional[float]:
        return _safe_mean([t.cache_hit_rate for t in self.tasks])

    @property
    def mean_files_modified(self) -> Optional[float]:
        return _safe_mean([t.files_modified for t in self.tasks])

    @property
    def error_rate(self) -> Optional[float]:
        """Fraction of tasks with non-None error_fingerprint."""
        if not self.tasks:
            return None
        errored = sum(1 for t in self.tasks if t.error_fingerprint is not None)
        return errored / len(self.tasks)

    @property
    def mean_conversation_turns(self) -> Optional[float]:
        return _safe_mean([t.conversation_turns for t in self.tasks])

    @property
    def mean_tool_errors(self) -> Optional[float]:
        return _safe_mean([t.tool_errors_total for t in self.tasks])

    @property
    def mean_backtrack_count(self) -> Optional[float]:
        return _safe_mean([t.backtrack_count for t in self.tasks])

    @property
    def mean_mcp_latency_p50(self) -> Optional[float]:
        return _safe_mean([t.mcp_latency_p50_ms for t in self.tasks])

    @property
    def mean_context_window_peak(self) -> Optional[float]:
        return _safe_mean([t.context_window_peak_pct for t in self.tasks])

    @property
    def error_fingerprint_summary(self) -> Optional[dict[str, int]]:
        """Count of each error fingerprint_id across tasks."""
        counts: dict[str, int] = {}
        for t in self.tasks:
            if t.error_fingerprint and isinstance(t.error_fingerprint, dict):
                fid = t.error_fingerprint.get("fingerprint_id", "unknown")
                counts[fid] = counts.get(fid, 0) + 1
        return counts if counts else None

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
            "mean_judge_score": self.mean_judge_score,
            "judge_coverage": self.judge_coverage,
            "pass_rate": self.pass_rate,
            "mean_tokens": self.mean_tokens,
            "mean_wall_clock": self.mean_wall_clock,
            "mean_agent_execution": self.mean_agent_execution,
            "mean_verifier": self.mean_verifier,
            "mean_mcp_ratio": self.mean_mcp_ratio,
            "mean_deepsearch_keyword_ratio": self.mean_deepsearch_keyword_ratio,
            "mean_input_output_ratio": self.mean_input_output_ratio,
            "mean_cache_hit_rate": self.mean_cache_hit_rate,
            "mean_files_modified": self.mean_files_modified,
            "error_rate": self.error_rate,
            "mean_conversation_turns": self.mean_conversation_turns,
            "mean_tool_errors": self.mean_tool_errors,
            "mean_backtrack_count": self.mean_backtrack_count,
            "mean_mcp_latency_p50": self.mean_mcp_latency_p50,
            "mean_context_window_peak": self.mean_context_window_peak,
            "error_fingerprint_summary": self.error_fingerprint_summary,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RunMetrics:
        tasks_data = data.pop("tasks", [])
        # Remove computed properties that may be in serialized form
        for key in ("mean_reward", "mean_partial_score", "mean_judge_score",
                     "judge_coverage", "pass_rate",
                     "mean_tokens", "mean_wall_clock",
                     "mean_agent_execution", "mean_verifier",
                     "mean_mcp_ratio",
                     "mean_deepsearch_keyword_ratio", "mean_input_output_ratio",
                     "mean_cache_hit_rate", "mean_files_modified",
                     "error_rate", "mean_conversation_turns", "mean_tool_errors",
                     "mean_backtrack_count", "mean_mcp_latency_p50",
                     "mean_context_window_peak", "error_fingerprint_summary"):
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
