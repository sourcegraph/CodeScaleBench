"""Comparison Builder - creates comparison.json for paired runs.

Computes deltas between baseline and MCP runs for paired comparisons.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from lib.matrix.expander import PairSpec
from lib.runner.pair_scheduler import PairExecution

if TYPE_CHECKING:
    from lib.exporter.canonical import V2Exporter


@dataclass
class PairComparison:
    """Comparison results for a baseline + MCP pair."""
    schema_version: str = "1.0.0"
    
    pair_id: str = ""
    experiment_id: str = ""
    invariant_hash: str = ""
    
    invariants: dict = field(default_factory=dict)
    baseline_run: dict = field(default_factory=dict)
    mcp_run: dict = field(default_factory=dict)
    
    delta_summary: dict = field(default_factory=dict)
    per_task_deltas: list[dict] = field(default_factory=list)
    outcome_breakdown: dict = field(default_factory=dict)


class ComparisonBuilder:
    """Builds comparison.json files for paired runs."""
    
    SCHEMA_VERSION = "1.0.0"
    
    def __init__(self, output_root: str | Path = "runs"):
        self.output_root = Path(output_root)
    
    def build_comparison(
        self,
        pair_exec: PairExecution,
        experiment_id: str,
        exporter: "V2Exporter"
    ) -> Path | None:
        """Build comparison.json for a pair.
        
        Args:
            pair_exec: The pair execution with results
            experiment_id: Parent experiment ID
            exporter: V2Exporter instance for reading results
            
        Returns:
            Path to comparison.json or None on failure
        """
        pair_spec = pair_exec.pair_spec
        
        baseline_results = self._load_run_results(
            experiment_id, pair_spec.baseline_run_id
        )
        mcp_results = self._load_run_results(
            experiment_id, pair_spec.mcp_run_id
        )
        
        if not baseline_results or not mcp_results:
            return self._write_error_comparison(
                pair_spec, experiment_id,
                "Could not load results for one or both runs"
            )
        
        comparison = PairComparison(
            schema_version=self.SCHEMA_VERSION,
            pair_id=pair_spec.pair_id,
            experiment_id=experiment_id,
            invariant_hash=pair_spec.invariant_hash,
        )
        
        comparison.invariants = {
            "benchmark": pair_spec.benchmark,
            "task_ids": pair_spec.task_ids,
            "model": pair_spec.model,
            "seed": pair_spec.seed,
        }
        
        comparison.baseline_run = {
            "run_id": pair_spec.baseline_run_id,
            "mcp_mode": "baseline",
            "summary_metrics": baseline_results.get("summary_metrics", {}),
        }
        
        comparison.mcp_run = {
            "run_id": pair_spec.mcp_run_id,
            "mcp_mode": pair_spec.mcp_mode,
            "summary_metrics": mcp_results.get("summary_metrics", {}),
        }
        
        comparison.delta_summary = self._compute_delta_summary(
            baseline_results, mcp_results
        )
        
        comparison.per_task_deltas = self._compute_per_task_deltas(
            baseline_results, mcp_results
        )
        
        comparison.outcome_breakdown = self._compute_outcome_breakdown(
            comparison.per_task_deltas
        )
        
        return self._write_comparison(comparison, experiment_id)
    
    def _load_run_results(
        self,
        experiment_id: str,
        run_id: str
    ) -> dict | None:
        """Load results.json for a run."""
        results_path = (
            self.output_root / experiment_id / "runs" / run_id / "results.json"
        )
        
        if not results_path.exists():
            return None
        
        try:
            with open(results_path) as f:
                return json.load(f)
        except json.JSONDecodeError:
            return None
    
    def _compute_delta_summary(
        self,
        baseline: dict,
        mcp: dict
    ) -> dict:
        """Compute summary deltas between baseline and MCP."""
        baseline_metrics = baseline.get("summary_metrics", {})
        mcp_metrics = mcp.get("summary_metrics", {})
        
        baseline_rate = baseline_metrics.get("resolution_rate", 0.0)
        mcp_rate = mcp_metrics.get("resolution_rate", 0.0)
        rate_delta = mcp_rate - baseline_rate
        
        if baseline_rate > 0:
            rate_improvement_pct = (rate_delta / baseline_rate) * 100
        else:
            rate_improvement_pct = 100.0 if mcp_rate > 0 else 0.0
        
        baseline_reward = baseline_metrics.get("mean_reward", 0.0)
        mcp_reward = mcp_metrics.get("mean_reward", 0.0)
        reward_delta = mcp_reward - baseline_reward
        
        mcp_tool_usage = mcp.get("tool_usage", {})
        mcp_tool_calls = mcp_tool_usage.get("mcp_tool_calls", 0)
        
        baseline_timing = baseline.get("timing", {})
        mcp_timing = mcp.get("timing", {})
        baseline_duration = baseline_timing.get("duration_seconds", 0)
        mcp_duration = mcp_timing.get("duration_seconds", 0)
        duration_delta = mcp_duration - baseline_duration
        
        return {
            "resolution_rate_delta": rate_delta,
            "resolution_rate_improvement_pct": rate_improvement_pct,
            "mean_reward_delta": reward_delta,
            "mcp_tool_calls_total": mcp_tool_calls,
            "duration_delta_seconds": duration_delta,
        }
    
    def _compute_per_task_deltas(
        self,
        baseline: dict,
        mcp: dict
    ) -> list[dict]:
        """Compute per-task deltas between baseline and MCP."""
        baseline_tasks = {
            t["task_id"]: t
            for t in baseline.get("per_task_metrics", [])
        }
        mcp_tasks = {
            t["task_id"]: t
            for t in mcp.get("per_task_metrics", [])
        }
        
        all_task_ids = set(baseline_tasks.keys()) | set(mcp_tasks.keys())
        
        deltas = []
        for task_id in sorted(all_task_ids):
            baseline_task = baseline_tasks.get(task_id, {})
            mcp_task = mcp_tasks.get(task_id, {})
            
            baseline_resolved = baseline_task.get("resolved", False)
            mcp_resolved = mcp_task.get("resolved", False)
            
            baseline_reward = baseline_task.get("reward", 0.0) or 0.0
            mcp_reward = mcp_task.get("reward", 0.0) or 0.0
            
            baseline_duration = baseline_task.get("duration_seconds", 0) or 0
            mcp_duration = mcp_task.get("duration_seconds", 0) or 0
            
            if baseline_resolved and mcp_resolved:
                outcome = "both_pass"
            elif not baseline_resolved and not mcp_resolved:
                outcome = "both_fail"
            elif mcp_resolved and not baseline_resolved:
                outcome = "mcp_only_pass"
            else:
                outcome = "baseline_only_pass"
            
            delta = {
                "task_id": task_id,
                "baseline_resolved": baseline_resolved,
                "mcp_resolved": mcp_resolved,
                "baseline_reward": baseline_reward,
                "mcp_reward": mcp_reward,
                "reward_delta": mcp_reward - baseline_reward,
                "duration_delta_seconds": mcp_duration - baseline_duration,
                "outcome": outcome,
            }
            
            deltas.append(delta)
        
        return deltas
    
    def _compute_outcome_breakdown(self, deltas: list[dict]) -> dict:
        """Compute breakdown of outcomes across tasks."""
        outcomes = {
            "both_pass": 0,
            "both_fail": 0,
            "mcp_only_pass": 0,
            "baseline_only_pass": 0,
        }
        
        for delta in deltas:
            outcome = delta.get("outcome", "both_fail")
            if outcome in outcomes:
                outcomes[outcome] += 1
        
        return outcomes
    
    def _write_comparison(
        self,
        comparison: PairComparison,
        experiment_id: str
    ) -> Path:
        """Write comparison.json to file."""
        pair_dir = self.output_root / experiment_id / "pairs" / comparison.pair_id
        pair_dir.mkdir(parents=True, exist_ok=True)
        
        comparison_path = pair_dir / "comparison.json"
        
        comparison_dict = {
            "schema_version": comparison.schema_version,
            "pair_id": comparison.pair_id,
            "experiment_id": comparison.experiment_id,
            "invariant_hash": comparison.invariant_hash,
            "invariants": comparison.invariants,
            "baseline_run": comparison.baseline_run,
            "mcp_run": comparison.mcp_run,
            "delta_summary": comparison.delta_summary,
            "per_task_deltas": comparison.per_task_deltas,
            "outcome_breakdown": comparison.outcome_breakdown,
        }
        
        with open(comparison_path, "w") as f:
            json.dump(comparison_dict, f, indent=2)
        
        return comparison_path
    
    def _write_error_comparison(
        self,
        pair_spec: PairSpec,
        experiment_id: str,
        error_message: str
    ) -> Path:
        """Write an error comparison when results are unavailable."""
        pair_dir = self.output_root / experiment_id / "pairs" / pair_spec.pair_id
        pair_dir.mkdir(parents=True, exist_ok=True)
        
        comparison_dict = {
            "schema_version": self.SCHEMA_VERSION,
            "pair_id": pair_spec.pair_id,
            "experiment_id": experiment_id,
            "invariant_hash": pair_spec.invariant_hash,
            "error": {
                "error_class": "ComparisonError",
                "error_message": error_message,
            },
            "baseline_run": {"run_id": pair_spec.baseline_run_id},
            "mcp_run": {"run_id": pair_spec.mcp_run_id},
        }
        
        comparison_path = pair_dir / "comparison.json"
        with open(comparison_path, "w") as f:
            json.dump(comparison_dict, f, indent=2)
        
        return comparison_path
